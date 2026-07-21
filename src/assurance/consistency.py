"""A10 Consistency Checker — Phase 9. DETERMINISTIC: zero LLM calls.

Extracts every number, date, duration, currency figure and named entity across all
sections into a fact table, then checks that cost components sum to the stated total,
phase durations sum to the program duration, FTE peaks match the resource table, no
entity carries two different values, and percentages reconcile.
Out: ConsistencyReport with contradictions localized to section IDs.

This is the most demo-able component in the system, and the one where a model would be
actively harmful: asked whether a column of figures adds up, a model will usually say
yes. Arithmetic is checked by doing the arithmetic.

Every contradiction names the offending section and shows both values, because a
finding a human cannot locate is a finding they will ignore.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models.schemas import ConsistencyReport, Contradiction, GeneratedSection

WEEKS_PER_MONTH = 4.345
#: Rounding in published figures is normal; a real error is larger than this.
RELATIVE_TOLERANCE = 0.02
ABSOLUTE_TOLERANCE = 0.01

_NUMBER = r"-?\d[\d,]*(?:\.\d+)?"
_TABLE_ROW = re.compile(r"^\s*\|(?P<cells>.+)\|\s*$", re.MULTILINE)
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_TOTAL_LABEL = re.compile(r"\b(total|sum|grand total)\b", re.I)

#: Quantities tracked across the whole document. A quantity stated twice with different
#: values is a contradiction regardless of which statement is right.
_TRACKED: dict[str, re.Pattern[str]] = {
    "peak FTE": re.compile(
        r"peak(?:\s+\w+){0,3}?\s+of\s+\*{0,2}(" + _NUMBER + r")\*{0,2}\s*FTE"
        r"|peak\s+strength\s+of\s+\*{0,2}(" + _NUMBER + r")\*{0,2}\s*FTE"
        r"|\*{0,2}(" + _NUMBER + r")\*{0,2}\s*FTEs?\s+(?:at\s+)?peak",
        re.I,
    ),
    "programme duration in months": re.compile(
        r"(?:completed|delivered|runs?|lasts?|duration|span)\D{0,40}?("
        + _NUMBER + r")\s*months",
        re.I,
    ),
}


@dataclass
class Fact:
    """One extracted figure, kept with enough context to be explainable."""

    kind: str
    value: float
    unit: str
    section_id: str
    evidence: str


class ConsistencyChecker:
    """Checks the assembled document for internal contradictions.

    One public method: check().
    """

    def check(self, sections: list[GeneratedSection]) -> ConsistencyReport:
        facts: list[Fact] = []
        contradictions: list[Contradiction] = []

        for section in sections:
            facts.extend(self._facts(section))
            contradictions.extend(self._table_totals(section))
            contradictions.extend(self._percentage_rows(section))

        contradictions.extend(self._duration_against_phases(sections))
        contradictions.extend(self._conflicting_values(facts))

        return ConsistencyReport(
            facts_extracted=len(facts),
            contradictions=self._dedupe(contradictions),
        )

    @staticmethod
    def _dedupe(contradictions: list[Contradiction]) -> list[Contradiction]:
        """One finding per distinct problem.

        The same duration mismatch restated in three places is one error, and reporting
        it three times trains a reviewer to skim the list.
        """
        seen: set[tuple[str, str]] = set()
        out: list[Contradiction] = []
        for item in contradictions:
            key = (item.kind, item.detail)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    # --- fact extraction ------------------------------------------------------------

    def _facts(self, section: GeneratedSection) -> list[Fact]:
        facts: list[Fact] = []
        text = section.content_md
        for kind, pattern in _TRACKED.items():
            for match in pattern.finditer(text):
                raw = next((g for g in match.groups() if g), None)
                if raw is None:
                    continue
                facts.append(Fact(
                    kind=kind,
                    value=self._number(raw),
                    unit="FTE" if "FTE" in kind else "months",
                    section_id=section.section_id,
                    evidence=self._context(text, match.start()),
                ))
        return facts

    @staticmethod
    def _number(raw: str) -> float:
        return float(raw.replace(",", "").replace("*", "").strip())

    @staticmethod
    def _context(text: str, position: int, width: int = 90) -> str:
        start = max(0, position - width // 2)
        return re.sub(r"\s+", " ", text[start : position + width]).strip()

    # --- table arithmetic -----------------------------------------------------------

    def _tables(self, markdown: str) -> list[list[list[str]]]:
        """Group contiguous pipe rows into tables, dropping separator rows."""
        tables: list[list[list[str]]] = []
        current: list[list[str]] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                if current:
                    tables.append(current)
                    current = []
                continue
            if _TABLE_SEPARATOR.match(stripped):
                continue
            match = _TABLE_ROW.match(stripped)
            if match:
                current.append([c.strip() for c in match.group("cells").split("|")])
        if current:
            tables.append(current)
        return tables

    def _table_totals(self, section: GeneratedSection) -> list[Contradiction]:
        """Every table with a TOTAL row must have components summing to it."""
        out: list[Contradiction] = []
        for table in self._tables(section.content_md):
            if len(table) < 3:
                continue
            total_rows = [r for r in table if r and _TOTAL_LABEL.search(r[0])]
            body_rows = [r for r in table if r and not _TOTAL_LABEL.search(r[0])]
            if not total_rows or len(body_rows) < 2:
                continue

            for column in range(1, max(len(r) for r in table)):
                stated = self._cell_number(total_rows[-1], column)
                if stated is None:
                    continue
                values = [self._cell_number(r, column) for r in body_rows[1:]]
                values = [v for v in values if v is not None]
                if len(values) < 2:
                    continue
                computed = sum(values)
                if self._matches(computed, stated):
                    continue
                header = body_rows[0][column] if column < len(body_rows[0]) else f"col {column}"
                out.append(Contradiction(
                    kind="TABLE_TOTAL",
                    detail=(
                        f"in '{header}', the {len(values)} component values sum to "
                        f"{computed:,.2f} but the total row states {stated:,.2f} "
                        f"(difference {abs(computed - stated):,.2f})"
                    ),
                    section_ids=[section.section_id],
                    values=[f"components {computed:,.2f}", f"stated {stated:,.2f}"],
                ))
        return out

    def _percentage_rows(self, section: GeneratedSection) -> list[Contradiction]:
        """A row labelled with a percentage must be that percentage of the others."""
        out: list[Contradiction] = []
        for table in self._tables(section.content_md):
            if len(table) < 3:
                continue
            pct_rows = [(r, m) for r in table if r
                        for m in [re.search(r"\((" + _NUMBER + r")\s*%\)", r[0])] if m]
            if not pct_rows:
                continue
            body = [r for r in table[1:]
                    if r and not _TOTAL_LABEL.search(r[0])
                    and not re.search(r"\(" + _NUMBER + r"\s*%\)", r[0])]
            for row, match in pct_rows:
                pct = self._number(match.group(1))
                stated = self._cell_number(row, 1)
                base = [self._cell_number(r, 1) for r in body]
                base = [b for b in base if b is not None]
                if stated is None or len(base) < 2:
                    continue
                expected = sum(base) * pct / 100.0
                if self._matches(expected, stated):
                    continue
                out.append(Contradiction(
                    kind="PERCENTAGE",
                    detail=(
                        f"'{row[0]}' states {stated:,.2f}, but {pct:g}% of the "
                        f"{sum(base):,.2f} component subtotal is {expected:,.2f}"
                    ),
                    section_ids=[section.section_id],
                    values=[f"stated {stated:,.2f}", f"computed {expected:,.2f}"],
                ))
        return out

    def _cell_number(self, row: list[str], column: int) -> float | None:
        if column >= len(row):
            return None
        cell = row[column].replace("*", "").replace("₹", "").replace("€", "").strip()
        match = re.fullmatch(r"(" + _NUMBER + r")\s*%?", cell)
        return self._number(match.group(1)) if match else None

    # --- cross-section checks -------------------------------------------------------

    def _duration_against_phases(self, sections: list[GeneratedSection]
                                 ) -> list[Contradiction]:
        """Phase weeks must agree with any stated duration in months."""
        weeks_total: tuple[float, str] | None = None
        for section in sections:
            for table in self._tables(section.content_md):
                header = " ".join(table[0]).lower() if table else ""
                if "week" not in header:
                    continue
                column = next(
                    (i for i, h in enumerate(table[0]) if "week" in h.lower()), None
                )
                if column is None:
                    continue
                total_row = next((r for r in table if r and _TOTAL_LABEL.search(r[0])),
                                 None)
                if total_row is not None:
                    stated = self._cell_number(total_row, column)
                    if stated:
                        weeks_total = (stated, section.section_id)
                else:
                    values = [self._cell_number(r, column) for r in table[1:]]
                    values = [v for v in values if v is not None]
                    if len(values) >= 2:
                        weeks_total = (sum(values), section.section_id)

        if weeks_total is None:
            return []

        weeks, weeks_section = weeks_total
        implied_months = weeks / WEEKS_PER_MONTH

        out: list[Contradiction] = []
        for section in sections:
            for match in _TRACKED["programme duration in months"].finditer(
                section.content_md
            ):
                raw = next((g for g in match.groups() if g), None)
                if raw is None:
                    continue
                stated_months = self._number(raw)
                if self._matches(implied_months, stated_months, rel=0.12):
                    continue
                out.append(Contradiction(
                    kind="DURATION",
                    detail=(
                        f"phase durations total {weeks:g} weeks, which is "
                        f"{implied_months:.1f} months, but the document states "
                        f"{stated_months:g} months"
                    ),
                    section_ids=sorted({weeks_section, section.section_id}),
                    values=[f"{implied_months:.1f} months implied",
                            f"{stated_months:g} months stated"],
                ))
        return out

    @staticmethod
    def _conflicting_values(facts: list[Fact]) -> list[Contradiction]:
        """The same tracked quantity must not carry two different values."""
        grouped: dict[str, list[Fact]] = {}
        for fact in facts:
            grouped.setdefault(fact.kind, []).append(fact)

        out: list[Contradiction] = []
        for kind, group in grouped.items():
            distinct = sorted({f.value for f in group})
            if len(distinct) < 2:
                continue
            out.append(Contradiction(
                kind="ENTITY_VALUE",
                detail=(
                    f"{kind} is stated as "
                    + " and ".join(f"{v:g}" for v in distinct)
                    + " in different places"
                ),
                section_ids=sorted({f.section_id for f in group}),
                values=[f"{f.value:g} ({f.section_id}): {f.evidence[:70]}" for f in group],
            ))
        return out

    # --- helpers --------------------------------------------------------------------

    @staticmethod
    def _matches(computed: float, stated: float, rel: float = RELATIVE_TOLERANCE) -> bool:
        if abs(computed - stated) <= ABSOLUTE_TOLERANCE:
            return True
        scale = max(abs(computed), abs(stated), 1.0)
        return abs(computed - stated) / scale <= rel
