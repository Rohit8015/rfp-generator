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
        gap_ids = {m.requirement_id for m in (proof_matches or []) if m.fit is Fit.GAP}
        carved_out = [
            r for r in section_reqs
            if r.id in gap_ids or _GUARDED_TOPICS.search(r.text)
        ]
        carved_ids = {r.id for r in carved_out}
        evidenced = [r for r in section_reqs if r.id not in carved_ids]

        reason = self.guardrail_reason(section, section_reqs, proof_matches or [])
        if reason:
            generated = self._stakeholder_brief(section, section_reqs, reason)
        else:
            generated = self._dispatch(section, buyer, pack, evidenced, themes or [],
                                       failure_reason)
            if carved_out and generated.status is SectionStatus.DRAFTED:
                self._carve_out(generated, carved_out)

        provenance.verify_complete(generated)
        return generated

    @staticmethod
    def _carve_out(section: GeneratedSection, requirements: list[Requirement]) -> None:
        """Draft what is evidenced; hand the rest to a human, in the section itself.

        One unevidenced requirement should not block a section covering nine others.
        A bid team drafts what it can prove and carves out the rest, and the carve-out
        must be visible in the document rather than living only in a task list.

        The note carries STAKEHOLDER provenance, so the section correctly stops counting
        as automated: it did need a human.
        """
        lines = [
            "",
            "> **Requires input before submission.** The following requirements in this "
            "section are unevidenced or are compliance and legal matters, and have not "
            "been drafted:",
        ]
        lines += [f"> - {r.id} ({r.priority.value}): {r.text}" for r in requirements]
        addition = "\n".join(lines) + "\n"

        section.content_md = section.content_md.rstrip() + "\n" + addition
        section.sentences.extend(provenance.record_sentences(
            section.section_id, addition, ProvenanceKind.STAKEHOLDER,
            start_index=len(section.sentences),
        ))

    # --- guardrail ------------------------------------------------------------------

    @staticmethod
    def guardrail_reason(
        section: OutlineSection,
        requirements: list[Requirement],
        proof_matches: list[ProofMatch],
    ) -> str | None:
        """Why this section must go to a human, or None if it may be drafted.

        A GAP escalates the whole section only when EVERY requirement in it is a GAP.
        A section with one unevidenced requirement among nine is still worth drafting;
        the odd one out is carved out visibly instead. Escalating the lot would hand a
        human nine requirements they did not need to write.
        """
        gaps = {m.requirement_id for m in proof_matches if m.fit is Fit.GAP}
        gap_hits = [r.id for r in requirements if r.id in gaps]
        if requirements and len(gap_hits) == len(requirements):
            return (
                "every requirement in this section lacks a supporting proof point: "
                + ", ".join(sorted(gap_hits))
            )

        haystack = f"{section.title} {section.purpose}"
        if _GUARDED_TOPICS.search(haystack):
            return f"section subject matter is compliance or legal: {section.title}"

        # An individual compliance or legal requirement inside an otherwise ordinary
        # section is carved out, not escalated with the whole section. Escalating the lot
        # would hand a human nine requirements they did not need to write, which is the
        # same mistake the GAP rule made before it was narrowed.
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

        if form is DeliverableForm.COSTING:
            return self._costing(section)

        if form in (DeliverableForm.GANTT, DeliverableForm.CHART):
            return self._visual(section)

        return self._narrative.write(section, buyer, pack, themes, failure_reason)

    def _costing(self, section: OutlineSection) -> GeneratedSection:
        """Deterministic cost model. Escalates rather than inventing figures."""
        try:
            return self._quant.write(section)
        except Exception as exc:  # noqa: BLE001 - no parameters means no cost model
            log.warning("cost model unavailable for %s: %s", section.id, exc)
            return self._stakeholder_brief(
                section, [],
                f"a cost model needs programme parameters, which are not available "
                f"for this bid ({type(exc).__name__})",
            )

    def _visual(self, section: OutlineSection) -> GeneratedSection:
        """Charts, drawn from the same cost model that produces the cost table.

        A Gantt built from different numbers than the cost table is the classic
        proposal error, so both read one model.
        """
        try:
            model = self._quant.build(self._quant.load_params("standard"))
            return self._visual_generator.write(section, model=model)
        except Exception as exc:  # noqa: BLE001
            log.warning("charts unavailable for %s: %s", section.id, exc)
            return self._stakeholder_brief(
                section, [],
                f"charts need programme parameters, which are not available for this "
                f"bid ({type(exc).__name__})",
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

    @property
    def _quant(self):
        if "quant" not in self._writers:
            from src.writers.quant_modeler import QuantModeler

            self._writers["quant"] = QuantModeler(self.settings)
        return self._writers["quant"]

    @property
    def _visual_generator(self):
        if "visual" not in self._writers:
            from src.writers.visual_generator import VisualGenerator

            self._writers["visual"] = VisualGenerator(self.settings)
        return self._writers["visual"]


def stakeholder_pack(section_id: str) -> ContextPack:
    """A pack for a section that will not be drafted. Needs no calibration."""
    return ContextPack(
        query=section_id, reuse_decision=ReuseDecision.STAKEHOLDER, confidence=0.0
    )
