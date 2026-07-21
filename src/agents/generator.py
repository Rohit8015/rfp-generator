"""A9 Generation Router — Phase 7.

Routes on deliverable_form to the writers in src/writers/.
Guardrail: Compliance, Legal and any GAP requirement force STAKEHOLDER and are never
LLM-drafted as final. Every emitted sentence carries a provenance record.

The guardrail is checked BEFORE any writer is chosen, not after drafting. Generating
compliance prose and then discarding it would still have spent the call, and worse, the
draft would exist -- and drafts get copied. A stakeholder brief is written instead: it
states what is needed and from whom, and carries STAKEHOLDER provenance so it can never
be counted as automated.

Provenance completeness is enforced here rather than trusted to each writer, so a new
writer cannot forget.
"""

from __future__ import annotations

import logging
import re

from src.models.schemas import (
    BuyerProfile,
    ContextPack,
    DeliverableForm,
    Fit,
    GeneratedSection,
    OutlineSection,
    ProofMatch,
    ProvenanceKind,
    Requirement,
    ReuseDecision,
    SectionStatus,
    WinTheme,
)
from src.utils import provenance

log = logging.getLogger(__name__)

#: Subject matter that a human must own, whatever the retrieval says.
_GUARDED_TOPICS = re.compile(
    r"\b(complian\w+|regulat\w+|legal|liabilit\w+|indemnit\w+|warrant\w+|"
    r"contractual|terms and conditions|penalt\w+|litigation|insurance|"
    r"data protection act|gdpr|dpdp|rbi guidelines?|statutory)\b",
    re.I,
)


class GenerationRouter:
    """Routes a section to the right writer. One public method: generate()."""

    def __init__(self, provider=None, settings=None, writers: dict | None = None) -> None:
        self._provider = provider
        self.settings = settings
        self._writers = writers or {}

    # --- public ---------------------------------------------------------------------

    def generate(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        requirements: list[Requirement] | None = None,
        themes: list[WinTheme] | None = None,
        proof_matches: list[ProofMatch] | None = None,
        failure_reason: str | None = None,
    ) -> GeneratedSection:
        requirements = requirements or []
        section_reqs = [r for r in requirements if r.id in set(section.requirement_ids)]

        reason = self.guardrail_reason(section, section_reqs, proof_matches or [])
        if reason:
            generated = self._stakeholder_brief(section, section_reqs, reason)
        else:
            generated = self._dispatch(section, buyer, pack, section_reqs, themes or [],
                                       failure_reason)

        provenance.verify_complete(generated)
        return generated

    # --- guardrail ------------------------------------------------------------------

    @staticmethod
    def guardrail_reason(
        section: OutlineSection,
        requirements: list[Requirement],
        proof_matches: list[ProofMatch],
    ) -> str | None:
        """Why this section must go to a human, or None if it may be drafted."""
        gaps = {m.requirement_id for m in proof_matches if m.fit is Fit.GAP}
        gap_hits = [r.id for r in requirements if r.id in gaps]
        if gap_hits:
            return (
                "covers requirements with no supporting proof point: "
                + ", ".join(sorted(gap_hits))
            )

        haystack = f"{section.title} {section.purpose}"
        if _GUARDED_TOPICS.search(haystack):
            return f"section subject matter is compliance or legal: {section.title}"

        guarded_reqs = [r.id for r in requirements if _GUARDED_TOPICS.search(r.text)]
        if guarded_reqs:
            return (
                "covers compliance or legal requirements: " + ", ".join(sorted(guarded_reqs))
            )
        return None

    @staticmethod
    def _stakeholder_brief(
        section: OutlineSection, requirements: list[Requirement], reason: str
    ) -> GeneratedSection:
        """A brief for a human, not a draft. Never counted as automated."""
        lines = [
            f"## {section.title}",
            "",
            "This section requires human authorship and has not been drafted.",
            f"Reason: {reason}.",
            "",
            "Requirements to be addressed by the owner:",
        ]
        lines += [f"- {r.id} ({r.priority.value}): {r.text}" for r in requirements] or [
            "- none itemised"
        ]
        content = "\n".join(lines) + "\n"

        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, ProvenanceKind.STAKEHOLDER
            ),
            status=SectionStatus.ESCALATED,
        )

    # --- dispatch -------------------------------------------------------------------

    def _dispatch(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        requirements: list[Requirement],
        themes: list[WinTheme],
        failure_reason: str | None,
    ) -> GeneratedSection:
        form = section.deliverable_form

        if form in (DeliverableForm.APPENDIX,):
            return self._boilerplate.write(section, buyer)

        if form in (DeliverableForm.TABLE, DeliverableForm.MATRIX):
            return self._structured.write(section, buyer, pack, requirements,
                                          failure_reason)

        if form in (DeliverableForm.COSTING, DeliverableForm.GANTT, DeliverableForm.CHART):
            # Phase 8 owns these. Until then they are escalated rather than guessed at
            # in prose, which would put invented numbers in front of a client.
            return self._deferred(section, form)

        return self._narrative.write(section, buyer, pack, themes, failure_reason)

    @staticmethod
    def _deferred(section: OutlineSection, form: DeliverableForm) -> GeneratedSection:
        content = (
            f"## {section.title}\n\n"
            f"This section renders as {form.value} and is produced by the deterministic "
            f"{'cost model' if form is DeliverableForm.COSTING else 'visual generator'}, "
            f"which is not yet wired in.\n"
        )
        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, ProvenanceKind.STAKEHOLDER
            ),
            status=SectionStatus.ESCALATED,
        )

    # --- writers --------------------------------------------------------------------

    @property
    def _narrative(self):
        if "narrative" not in self._writers:
            from src.writers.narrative import NarrativeWriter

            self._writers["narrative"] = NarrativeWriter(self._provider)
        return self._writers["narrative"]

    @property
    def _structured(self):
        if "structured" not in self._writers:
            from src.writers.structured import StructuredWriter

            self._writers["structured"] = StructuredWriter(self._provider)
        return self._writers["structured"]

    @property
    def _boilerplate(self):
        if "boilerplate" not in self._writers:
            from src.writers.boilerplate import BoilerplateWriter

            self._writers["boilerplate"] = BoilerplateWriter(self.settings)
        return self._writers["boilerplate"]


def stakeholder_pack(section_id: str) -> ContextPack:
    """A pack for a section that will not be drafted. Needs no calibration."""
    return ContextPack(
        query=section_id, reuse_decision=ReuseDecision.STAKEHOLDER, confidence=0.0
    )
