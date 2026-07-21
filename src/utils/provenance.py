"""Provenance tracking — Phase 7.

Contract: records a provenance_kind (REUSED / ADAPTED / SYNTHESIZED / TEMPLATE /
COMPUTED / STAKEHOLDER) and source IDs for every generated sentence. No untracked text
may reach the assembled output.

The design point: provenance is not attached after writing, it is produced *by* writing.
A writer returns text and its records together, and `verify_complete` refuses a section
whose prose and records disagree. Retrofitting attribution onto finished prose is
guesswork, and guessed attribution is worse than none because it looks authoritative.

Markdown structure (headings, table rows, bullets) is deliberately excluded from the
sentence count. A table's provenance belongs to its rows, not to its pipe characters.
"""

from __future__ import annotations

import re

from src.models.schemas import (
    DeliverableForm,
    GeneratedSection,
    ProvenanceKind,
    ProvenanceRecord,
    ReuseDecision,
)
from src.utils import docparse

#: reuse_decision -> the provenance kind a writer should emit for text built that way.
DECISION_TO_KIND: dict[ReuseDecision, ProvenanceKind] = {
    ReuseDecision.REUSE: ProvenanceKind.REUSED,
    ReuseDecision.ADAPT: ProvenanceKind.ADAPTED,
    ReuseDecision.SYNTHESIZE: ProvenanceKind.SYNTHESIZED,
    ReuseDecision.STAKEHOLDER: ProvenanceKind.STAKEHOLDER,
}

_STRUCTURAL = re.compile(r"^\s*(#{1,6}\s|\||[-*+]\s*$|>\s*$|```)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def is_structural(line: str) -> bool:
    """Markdown scaffolding that carries no claim of its own."""
    stripped = line.strip()
    if not stripped:
        return True
    if _TABLE_SEPARATOR.match(stripped):
        return True
    return bool(_STRUCTURAL.match(stripped)) and not stripped.startswith("|")


def prose_sentences(markdown: str) -> list[str]:
    """Sentences that carry a claim, ignoring headings, fences and table rules.

    Table *rows* are kept -- a row asserts something and needs provenance. Table
    *separators* are not.
    """
    out: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if _TABLE_SEPARATOR.match(stripped):
            # The line above a separator is the header row. It names columns rather
            # than asserting anything, so it is scaffolding like the separator itself.
            if out and out[-1].startswith("|"):
                out.pop()
            continue
        if re.match(r"^#{1,6}\s", stripped):
            continue
        if stripped.startswith("|"):
            out.append(docparse.normalize(stripped))
            continue
        bullet = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", stripped)
        out.extend(docparse.split_sentences(bullet))
    return [s for s in out if s.strip()]


def record_sentences(
    section_id: str,
    markdown: str,
    kind: ProvenanceKind,
    source_ids: list[str] | None = None,
    confidence: float | None = None,
    start_index: int = 0,
) -> list[ProvenanceRecord]:
    """Attach one provenance record per claim-bearing sentence.

    Used by writers whose whole output shares a provenance (a template fill, a computed
    table). Writers that mix kinds build records sentence by sentence instead.
    """
    ids = list(source_ids or [])
    records: list[ProvenanceRecord] = []
    for offset, sentence in enumerate(prose_sentences(markdown)):
        records.append(ProvenanceRecord(
            section_id=section_id,
            sentence_index=start_index + offset,
            sentence=sentence,
            kind=kind,
            source_ids=ids if kind not in _NO_SOURCE_KINDS else [],
            confidence=confidence,
        ))
    return records


#: Kinds that assert nothing traceable to a retrieved source.
_NO_SOURCE_KINDS = {
    ProvenanceKind.TEMPLATE, ProvenanceKind.COMPUTED, ProvenanceKind.STAKEHOLDER
}


class ProvenanceError(AssertionError):
    """Raised when text would reach the output without attribution."""


def verify_complete(section: GeneratedSection) -> None:
    """Refuse a section whose prose and provenance records disagree.

    This is the enforcement point for "no untracked text reaches output". It is called
    by the router after every writer, so a writer cannot forget.
    """
    claims = prose_sentences(section.content_md)
    if not claims:
        if section.content_md.strip() and section.deliverable_form is not DeliverableForm.CHART:
            raise ProvenanceError(
                f"{section.section_id}: content present but no claim-bearing sentence "
                f"was found; provenance cannot be verified"
            )
        return

    if len(section.sentences) != len(claims):
        raise ProvenanceError(
            f"{section.section_id}: {len(claims)} claim sentences but "
            f"{len(section.sentences)} provenance records"
        )

    indices = [r.sentence_index for r in section.sentences]
    if sorted(indices) != list(range(len(claims))):
        raise ProvenanceError(
            f"{section.section_id}: provenance indices are not a contiguous run: {indices}"
        )

    for record in section.sentences:
        if record.section_id != section.section_id:
            raise ProvenanceError(
                f"provenance record points at {record.section_id}, "
                f"inside section {section.section_id}"
            )


def coverage(section: GeneratedSection) -> float:
    """Share of claim sentences carrying a provenance record."""
    claims = prose_sentences(section.content_md)
    if not claims:
        return 1.0
    return min(1.0, len(section.sentences) / len(claims))


def summarize(sections: list[GeneratedSection]) -> dict[str, int]:
    """Sentence counts per provenance kind, for the automation report."""
    counts: dict[str, int] = {}
    for section in sections:
        for record in section.sentences:
            counts[record.kind.value] = counts.get(record.kind.value, 0) + 1
    return counts


def render_with_markers(section: GeneratedSection) -> str:
    """Content annotated with inline provenance, for the dashboard and for review."""
    by_sentence = {r.sentence: r for r in section.sentences}
    lines: list[str] = []
    for line in section.content_md.splitlines():
        annotated = line
        for sentence, record in by_sentence.items():
            if sentence and sentence in line:
                marker = record.kind.value
                if record.source_ids:
                    marker += "(" + ",".join(record.source_ids) + ")"
                annotated = annotated.replace(sentence, f"{sentence} [{marker}]")
        lines.append(annotated)
    return "\n".join(lines)
