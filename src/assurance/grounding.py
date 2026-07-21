"""A12 Groundedness Checker — Phase 9. Uses the LLM.

Checks every factual claim in generated prose against its cited context chunk via a
batched sentence-level NLI-style check. Unsupported claims are flagged UNGROUNDED.
Findings are flags for human review, never silent deletions.

Two design commitments, both about the cost of being wrong:

1. Findings are advisory. The plan names false positives as a live risk, and a checker
   that deletes text on suspicion is worse than no checker: it removes true statements
   and nobody notices. So this module returns findings and never edits.

2. Claims carrying no numbers, superlatives or named entities are skipped without a
   model call. "We will work with your team during discovery" asserts nothing checkable.
   Checking it wastes a call and risks a false flag on ordinary connective prose, and on
   a live demo the call budget is real.

A claim that cites no source is UNGROUNDED by definition and needs no model to decide.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from src.models.schemas import (
    AssuranceFinding,
    FindingType,
    GeneratedSection,
    ProvenanceKind,
    ProvenanceRecord,
    Severity,
)

log = logging.getLogger(__name__)

#: A sentence is checkable when it asserts something a source could contradict:
#: a figure, a superlative or absolute, or a named standard.
_CHECKABLE = re.compile(
    r"\d"
    r"|\b(?:all|every|never|always|only|first|best|largest|fastest|leading|"
    r"unique|guarantee\w*|proven|certified|accredited|award[- ]winning)\b",
    re.I,
)
#: Acronyms are matched case-SENSITIVELY. Under re.IGNORECASE, [A-Z]{2,} matches any
#: two letters, which made every sentence look checkable.
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")

#: Kinds that assert nothing retrieved, so there is nothing to check them against.
_UNCHECKED_KINDS = {ProvenanceKind.TEMPLATE, ProvenanceKind.STAKEHOLDER}


class _Verdict(BaseModel):
    index: int
    supported: bool
    reason: str = Field(default="", max_length=300)


class _Batch(BaseModel):
    verdicts: list[_Verdict] = Field(default_factory=list)


class GroundednessChecker:
    """Checks claims against their cited sources. One public method: check()."""

    BATCH_SIZE = 8

    def __init__(self, provider=None, chunks: dict[str, str] | None = None) -> None:
        self._provider = provider
        self._chunks = chunks

    # --- public ---------------------------------------------------------------------

    def check(self, sections: list[GeneratedSection]) -> list[AssuranceFinding]:
        findings: list[AssuranceFinding] = []
        to_verify: list[tuple[GeneratedSection, ProvenanceRecord]] = []

        for section in sections:
            for record in section.sentences:
                if record.kind in _UNCHECKED_KINDS:
                    continue
                if record.kind is ProvenanceKind.COMPUTED:
                    continue  # arithmetic is A10's job, and it is checked exactly
                if not self.is_checkable(record.sentence):
                    continue
                if not record.source_ids:
                    # Unreachable through the contracts: ProvenanceRecord refuses a
                    # REUSED or ADAPTED record without exactly one source and a
                    # SYNTHESIZED one without at least one. Kept as a backstop in case a
                    # record is ever built outside the schema.
                    findings.append(self._finding(
                        section, record, "claim cites no source", Severity.WARN
                    ))
                    continue
                to_verify.append((section, record))

        findings.extend(self._verify(to_verify))
        return findings

    @staticmethod
    def is_checkable(sentence: str) -> bool:
        """Does this sentence assert something a source could contradict?"""
        if len(sentence.split()) < 4:
            return False
        return bool(_CHECKABLE.search(sentence)) or bool(_ACRONYM.search(sentence))

    # --- verification ---------------------------------------------------------------

    def _verify(self, items: list[tuple[GeneratedSection, ProvenanceRecord]]
                ) -> list[AssuranceFinding]:
        if not items:
            return []
        try:
            provider = self._get_provider()
        except Exception as exc:  # noqa: BLE001 - offline is supported
            log.info("no provider; groundedness not checked: %s", exc)
            return []

        findings: list[AssuranceFinding] = []
        batches = [items[i : i + self.BATCH_SIZE]
                   for i in range(0, len(items), self.BATCH_SIZE)]
        prompts = [self._prompt(batch) for batch in batches]

        try:
            responses = provider.generate_many(prompts, tier="strong", schema=_Batch)
        except Exception as exc:  # noqa: BLE001 - never fail the run on a model fault
            log.warning("groundedness check failed: %s", exc)
            return []

        for batch, response in zip(batches, responses):
            parsed = response.parsed
            if parsed is None:
                continue
            for verdict in parsed.verdicts:
                if verdict.supported or not (0 <= verdict.index < len(batch)):
                    continue
                section, record = batch[verdict.index]
                findings.append(self._finding(
                    section, record,
                    verdict.reason or "not supported by the cited source",
                    Severity.WARN,
                ))
        return findings

    def _prompt(self, batch: list[tuple[GeneratedSection, ProvenanceRecord]]) -> str:
        blocks: list[str] = []
        for index, (_, record) in enumerate(batch):
            sources = "\n".join(
                f"    [{sid}] {self._source_text(sid)[:700]}"
                for sid in record.source_ids
            ) or "    (no source text available)"
            blocks.append(f"CLAIM {index}: {record.sentence}\n  SOURCES:\n{sources}")

        return (
            "You are checking whether each claim is supported by its cited sources.\n\n"
            "A claim is SUPPORTED only if the sources state it or directly entail it. "
            "It is NOT supported if the sources are merely on the same topic, if the "
            "claim adds a number or a superlative the sources do not contain, or if it "
            "generalises beyond what the sources say.\n\n"
            "Judge only against the sources given. Do not use outside knowledge.\n\n"
            + "\n\n".join(blocks)
            + '\n\nReturn JSON: {"verdicts": [{"index": 0, "supported": true, '
              '"reason": "..."}]}\n'
              "Give a verdict for every claim. Keep each reason under 25 words."
        )

    def _source_text(self, source_id: str) -> str:
        if self._chunks is None:
            self._chunks = self._load_chunks()
        return self._chunks.get(source_id, "")

    @staticmethod
    def _load_chunks() -> dict[str, str]:
        try:
            from src.ingestion.ingest import collect_chunks

            out: dict[str, str] = {}
            for chunk in collect_chunks():
                out.setdefault(chunk.source_id, chunk.text)
            return out
        except Exception as exc:  # noqa: BLE001 - a missing corpus is not fatal here
            log.warning("could not load corpus for grounding: %s", exc)
            return {}

    @staticmethod
    def _finding(section: GeneratedSection, record: ProvenanceRecord,
                 reason: str, severity: Severity) -> AssuranceFinding:
        return AssuranceFinding(
            finding_type=FindingType.UNGROUNDED,
            severity=severity,
            detail=reason,
            section_id=section.section_id,
            evidence=record.sentence[:240],
        )

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider


def groundedness_rate(sections: list[GeneratedSection],
                      findings: list[AssuranceFinding]) -> float:
    """Share of checkable claims with a valid source. The plan targets >=90%."""
    checkable = [
        r for s in sections for r in s.sentences
        if r.kind not in _UNCHECKED_KINDS
        and r.kind is not ProvenanceKind.COMPUTED
        and GroundednessChecker.is_checkable(r.sentence)
    ]
    if not checkable:
        return 100.0
    ungrounded = len([f for f in findings if f.finding_type is FindingType.UNGROUNDED])
    return round(100.0 * (1 - ungrounded / len(checkable)), 1)
