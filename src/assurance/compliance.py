"""A11 Compliance Verifier — Phase 9. DETERMINISTIC: zero LLM calls.

Traces every requirement to a section and a paragraph anchor.
Out: the RAG-coded requirements compliance matrix plus a coverage percentage.

This is the component a bid director would rely on. Missing one mandatory requirement
can disqualify a response outright regardless of how well it reads, and no human
reliably completes this checklist at 2am before a deadline.

Coverage is measured against what was actually WRITTEN, not against what the outline
planned. An outline that assigns a requirement to a section proves intent; only drafted
content proves delivery. A section that was planned, escalated and never written must
reduce coverage, or the matrix becomes a record of good intentions.
"""

from __future__ import annotations

import re

from src.models.schemas import (
    RAG,
    AssuranceFinding,
    ComplianceMatrix,
    ComplianceRow,
    FindingType,
    GeneratedSection,
    Priority,
    Requirement,
    ResponseOutline,
    SectionStatus,
    Severity,
)

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "with", "in", "on", "by", "is", "are",
    "be", "as", "at", "or", "that", "this", "it", "its", "from", "shall", "must",
    "should", "may", "will", "vendor", "supplier", "bidder", "provide", "include",
}

#: Share of a requirement's content words that must appear in the drafted section for it
#: to count as substantively addressed rather than merely assigned.
ADDRESSED_FLOOR = 0.30


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in _STOP and len(w) > 2}


class ComplianceVerifier:
    """Builds the compliance matrix. One public method: verify()."""

    def verify(
        self,
        requirements: list[Requirement],
        outline: ResponseOutline,
        sections: list[GeneratedSection],
    ) -> ComplianceMatrix:
        drafted = {
            s.section_id: s for s in sections
            if s.status in (SectionStatus.DRAFTED, SectionStatus.APPROVED)
        }
        planned = {rid: s.id for s in outline.sections for rid in s.requirement_ids}
        escalated = {s.section_id for s in sections
                     if s.status is SectionStatus.ESCALATED}

        rows: list[ComplianceRow] = []
        for requirement in requirements:
            section_id = planned.get(requirement.id)
            section = drafted.get(section_id) if section_id else None

            if section is None:
                rows.append(ComplianceRow(
                    requirement_id=requirement.id,
                    requirement_text=requirement.text,
                    priority=requirement.priority,
                    section_id=None,
                    anchor=(f"planned for {section_id}, escalated to a human"
                            if section_id in escalated else None),
                    rag=RAG.RED,
                ))
                continue

            anchor, strength = self._anchor(requirement, section)
            rows.append(ComplianceRow(
                requirement_id=requirement.id,
                requirement_text=requirement.text,
                priority=requirement.priority,
                section_id=section.section_id,
                anchor=anchor,
                rag=RAG.GREEN if strength >= ADDRESSED_FLOOR else RAG.AMBER,
            ))
        return ComplianceMatrix(rows=rows)

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _anchor(requirement: Requirement, section: GeneratedSection
                ) -> tuple[str | None, float]:
        """Locate the paragraph addressing this requirement, and how strongly."""
        wanted = _tokens(requirement.text)
        if not wanted:
            return section.section_id, 0.0

        best_index, best_score = None, 0.0
        paragraphs = [p for p in section.content_md.split("\n\n") if p.strip()]
        for index, paragraph in enumerate(paragraphs):
            overlap = len(wanted & _tokens(paragraph)) / len(wanted)
            if overlap > best_score:
                best_index, best_score = index, overlap

        if best_index is None:
            return section.section_id, 0.0
        return f"{section.section_id}#p{best_index + 1}", best_score


def coverage_findings(matrix: ComplianceMatrix) -> list[AssuranceFinding]:
    """Uncovered requirements as findings. A missed mandatory is a blocker."""
    findings: list[AssuranceFinding] = []
    for row in matrix.uncovered():
        findings.append(AssuranceFinding(
            finding_type=FindingType.UNCOVERED_REQ,
            severity=(Severity.BLOCKER if row.priority is Priority.MANDATORY
                      else Severity.WARN),
            detail=(f"{row.requirement_id} ({row.priority.value}) is not addressed by "
                    f"any drafted section"),
            requirement_id=row.requirement_id,
            evidence=row.requirement_text[:200],
        ))
    for row in matrix.rows:
        if row.rag is RAG.AMBER:
            findings.append(AssuranceFinding(
                finding_type=FindingType.UNCOVERED_REQ,
                severity=Severity.INFO,
                detail=(f"{row.requirement_id} is assigned to {row.section_id} but the "
                        f"drafted text only weakly addresses it"),
                requirement_id=row.requirement_id,
                section_id=row.section_id,
                evidence=row.anchor or "",
            ))
    return findings


def render_matrix(matrix: ComplianceMatrix) -> str:
    """The RAG-coded matrix as it appears in the delivered document."""
    symbol = {RAG.GREEN: "G", RAG.AMBER: "A", RAG.RED: "R"}
    covered = len(matrix.rows) - len(matrix.uncovered())
    lines = [
        "## Requirements compliance matrix",
        "",
        f"Coverage: **{matrix.coverage_pct:.1f}%** "
        f"({covered} of {len(matrix.rows)} requirements addressed)",
        "",
        "| Requirement | Priority | Section | Anchor | RAG |",
        "|---|---|---|---|---|",
    ]
    for row in matrix.rows:
        lines.append(
            f"| {row.requirement_id} | {row.priority.value} "
            f"| {row.section_id or '—'} | {row.anchor or '—'} | {symbol[row.rag]} |"
        )
    return "\n".join(lines) + "\n"
