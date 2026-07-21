"""Structured / tabular writer — Phase 7. Uses the LLM, schema-constrained.

Handles TABLE and MATRIX forms: emits typed rows, renders to markdown and docx tables.

The model returns rows as JSON against a pydantic schema, never markdown. Asking for a
formatted table invites malformed pipes, merged cells and inconsistent column counts,
and a table that renders wrong is worse than prose that reads badly -- a reviewer skims
tables and trusts them. Rendering is done in Python from validated rows, so the output
is well-formed by construction.

Each row carries its own source ids, so provenance is per row rather than per section:
a table where one row is evidenced and another invented would otherwise be indivisible.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.models.schemas import (
    BuyerProfile,
    ContextPack,
    GeneratedSection,
    OutlineSection,
    ProvenanceKind,
    ProvenanceRecord,
    Requirement,
    SectionStatus,
)
from src.utils import docparse, provenance

log = logging.getLogger(__name__)

MAX_COLUMNS = 6
MAX_ROWS = 25


class _Row(BaseModel):
    cells: list[str] = Field(min_length=1, max_length=MAX_COLUMNS)
    source_ids: list[str] = Field(default_factory=list)


class _Table(BaseModel):
    caption: str = ""
    headers: list[str] = Field(min_length=1, max_length=MAX_COLUMNS)
    rows: list[_Row] = Field(default_factory=list)


class StructuredWriter:
    """Drafts a table for one section. One public method: write()."""

    def __init__(self, provider=None) -> None:
        self._provider = provider

    # --- public ---------------------------------------------------------------------

    def write(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        requirements: list[Requirement] | None = None,
        failure_reason: str | None = None,
    ) -> GeneratedSection:
        prompt = self._prompt(section, buyer, pack, requirements or [], failure_reason)
        resp = self._get_provider().generate(prompt, tier="strong", schema=_Table)
        table = resp.parsed

        if table is None or not table.rows:
            return GeneratedSection(
                section_id=section.id,
                title=section.title,
                deliverable_form=section.deliverable_form,
                content_md="",
                status=SectionStatus.ESCALATED,
            )

        content, records = self._render(section, table, pack)
        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=records,
            status=SectionStatus.DRAFTED,
        )

    # --- rendering ------------------------------------------------------------------

    def _render(self, section: OutlineSection, table: _Table, pack: ContextPack
                ) -> tuple[str, list[ProvenanceRecord]]:
        width = len(table.headers)
        kind = provenance.DECISION_TO_KIND.get(
            pack.reuse_decision, ProvenanceKind.SYNTHESIZED
        )
        retrieved = {c.chunk_id for c in pack.candidates}

        lines = [f"## {section.title}", ""]
        if table.caption:
            lines += [table.caption.strip(), ""]
        lines.append("| " + " | ".join(self._cell(h) for h in table.headers) + " |")
        lines.append("|" + "---|" * width)

        records: list[ProvenanceRecord] = []
        caption_offset = 0
        if table.caption:
            for offset, sentence in enumerate(docparse.split_sentences(table.caption)):
                records.append(ProvenanceRecord(
                    section_id=section.id, sentence_index=offset, sentence=sentence,
                    kind=kind,
                    source_ids=self._sources(kind, list(retrieved)),
                    confidence=pack.confidence,
                ))
            caption_offset = len(records)

        for row_index, row in enumerate(table.rows[:MAX_ROWS]):
            cells = [self._cell(c) for c in row.cells[:width]]
            cells += [""] * (width - len(cells))
            rendered = "| " + " | ".join(cells) + " |"
            lines.append(rendered)

            # Keep only ids the retriever actually returned. A cited id the model
            # invented would be provenance theatre.
            cited = [s for s in row.source_ids if s in retrieved]
            row_kind = kind if cited else ProvenanceKind.SYNTHESIZED
            records.append(ProvenanceRecord(
                section_id=section.id,
                sentence_index=caption_offset + row_index,
                sentence=docparse.normalize(rendered),
                kind=row_kind,
                source_ids=self._sources(row_kind, cited or list(retrieved)),
                confidence=pack.confidence,
            ))

        return "\n".join(lines) + "\n", records

    @staticmethod
    def _sources(kind: ProvenanceKind, ids: list[str]) -> list[str]:
        if not ids:
            return []
        if kind in (ProvenanceKind.REUSED, ProvenanceKind.ADAPTED):
            return ids[:1]
        if kind is ProvenanceKind.SYNTHESIZED:
            return ids[:4]
        return []

    @staticmethod
    def _cell(value: str) -> str:
        """Pipes and newlines would break the table; escape rather than drop."""
        return docparse.normalize(str(value)).replace("|", "\\|") or "-"

    # --- prompt ---------------------------------------------------------------------

    def _prompt(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        requirements: list[Requirement],
        failure_reason: str | None,
    ) -> str:
        context = "\n\n".join(
            f"[{c.chunk_id}] {c.text[:900]}" for c in pack.candidates[:6]
        ) or "(no source material retrieved)"
        req_block = "\n".join(f"- {r.id}: {r.text}" for r in requirements[:12]) or "- none"

        prompt = (
            "Produce a table for one section of a proposal response.\n\n"
            f"SECTION: {section.title}\n"
            f"PURPOSE: {section.purpose}\n"
            f"AUDIENCE: {', '.join(buyer.audience_roles[:5]) or 'evaluation committee'}\n\n"
            f"REQUIREMENTS THIS TABLE MUST ADDRESS:\n{req_block}\n\n"
            f"SOURCE MATERIAL:\n{context}\n\n"
            "RULES\n"
            f"- At most {MAX_COLUMNS} columns and {MAX_ROWS} rows.\n"
            "- Every row must be supported by the source material. Put the source ids "
            "you used in that row's source_ids.\n"
            "- If a fact is not in the sources, omit the row. Do not fill gaps with "
            "plausible-sounding entries.\n"
            "- Cells are short: a phrase or a figure, not a paragraph.\n"
            "- Headers must be consistent across every row.\n\n"
            'Return JSON: {"caption": "...", "headers": ["..."], '
            '"rows": [{"cells": ["..."], "source_ids": ["..."]}]}'
        )
        if failure_reason:
            prompt += (
                f"\n\nTHIS TABLE FAILED REVIEW AND IS BEING REDRAWN.\n"
                f"Reason: {failure_reason}\nFix that specific problem.\n"
            )
        return prompt

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider
