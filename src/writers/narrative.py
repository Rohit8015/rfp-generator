"""Narrative (PROSE) writer — Phase 7. Uses the LLM.

Carries the BuyerProfile, the section's assigned win themes and the ContextPack.
Cites source IDs inline. Every sentence gets a provenance kind.

Provenance is derived from the retrieval decision, not from the model's own account of
what it did. A model asked to label its sentences REUSED or SYNTHESIZED will answer
plausibly and unreliably; the retriever already knows, because it made the decision that
produced the context. So a REUSE pack yields REUSED sentences, an ADAPT pack yields
ADAPTED, and so on -- the label describes how the text was *built*, which is a fact
about the pipeline rather than an opinion about the prose.

The buyer profile and themes are non-negotiable prompt content. A section written
without them is generic, and generic is what loses bids.
"""

from __future__ import annotations

import logging

from src.models.schemas import (
    BuyerProfile,
    ContextPack,
    GeneratedSection,
    OutlineSection,
    ProvenanceKind,
    ReuseDecision,
    SectionStatus,
    WinTheme,
)
from src.utils import provenance

log = logging.getLogger(__name__)

#: Retrieved context budget. Deliberately well inside the smallest context window in the
#: chain (llama-3.1-8b-instant), because a prompt that overflows is rejected by every
#: provider in turn and surfaces as AllProvidersFailed, which reads like an outage rather
#: than the size problem it is.
MAX_CONTEXT_CHARS = 4500
MAX_CANDIDATE_CHARS = 1100
#: If the full prompt still overflows, retry once on a much smaller context rather than
#: escalating a section a model could have written.
RETRY_CONTEXT_CHARS = 1500


class NarrativeWriter:
    """Drafts prose for one section. One public method: write()."""

    def __init__(self, provider=None) -> None:
        self._provider = provider

    # --- public ---------------------------------------------------------------------

    def write(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        themes: list[WinTheme] | None = None,
        failure_reason: str | None = None,
    ) -> GeneratedSection:
        """Draft the section. `failure_reason` feeds the Phase 10 regeneration loop."""
        provider = self._get_provider()
        prompt = self._prompt(section, buyer, pack, themes or [], failure_reason)
        # Cap the output. Left uncapped, a section with a 400-word target came back at
        # 22,953 characters, which is unreadable, unreviewable, and burns a free tier's
        # daily token budget in a handful of sections.
        budget = self._token_budget(section.target_words)
        try:
            resp = provider.generate(prompt, tier="strong", max_tokens=budget)
        except Exception as exc:  # noqa: BLE001 - one retry on a smaller context
            # Every provider refusing the same prompt is almost always an oversized
            # prompt rather than an outage: a section covering twenty requirements
            # carries a lot of retrieved text. Try once more with far less context
            # before giving the section to a human.
            log.warning("generation failed for %s (%s); retrying on a smaller context",
                        section.id, type(exc).__name__)
            prompt = self._prompt(section, buyer, pack, themes or [], failure_reason,
                                  context_budget=RETRY_CONTEXT_CHARS)
            resp = provider.generate(prompt, tier="strong", max_tokens=budget)

        content = self._clean(resp.text, section.title)
        kind = provenance.DECISION_TO_KIND.get(
            pack.reuse_decision, ProvenanceKind.SYNTHESIZED
        )
        source_ids = self._sources_for(kind, pack)

        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, kind, source_ids, confidence=pack.confidence
            ),
            status=SectionStatus.DRAFTED,
        )

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _token_budget(target_words: int) -> int:
        """Output cap for a section, from its target length.

        Roughly 1.4 tokens per word, doubled to leave room for markdown and for a
        section that legitimately runs long, then clamped so no single section can
        consume a disproportionate share of a free tier's daily budget.
        """
        return max(400, min(2200, int(target_words * 1.4 * 2)))

    @staticmethod
    def _sources_for(kind: ProvenanceKind, pack: ContextPack) -> list[str]:
        """REUSED and ADAPTED cite exactly one source; SYNTHESIZED cites several."""
        ids = [c.chunk_id for c in pack.candidates]
        if not ids:
            return []
        if kind in (ProvenanceKind.REUSED, ProvenanceKind.ADAPTED):
            return ids[:1]
        return ids[:4]

    def _prompt(
        self,
        section: OutlineSection,
        buyer: BuyerProfile,
        pack: ContextPack,
        themes: list[WinTheme],
        failure_reason: str | None,
        context_budget: int = MAX_CONTEXT_CHARS,
    ) -> str:
        context = self._format_context(pack, context_budget)
        theme_block = "\n".join(f"- {t.statement}" for t in themes) or "- none assigned"
        pains = "\n".join(f"- {p}" for p in buyer.stated_pains[:5]) or "- not stated"
        criteria = "\n".join(
            f"- {c.name}" + (f" (weight {c.weight})" if c.weight else "")
            for c in buyer.evaluation_criteria[:8]
        ) or "- not disclosed"
        red_lines = "\n".join(f"- {r}" for r in buyer.red_lines[:5]) or "- none stated"

        instruction = _DECISION_INSTRUCTION[pack.reuse_decision]

        prompt = (
            "You are drafting one section of a proposal response.\n\n"
            f"SECTION: {section.title}\n"
            f"PURPOSE: {section.purpose}\n"
            f"TARGET LENGTH: about {section.target_words} words\n\n"
            f"THE BUYER\n"
            f"Audience: {', '.join(buyer.audience_roles[:6]) or 'not stated'}\n"
            f"Tone to match: {buyer.tone_register}\n"
            f"Their stated pains:\n{pains}\n"
            f"How they will score this:\n{criteria}\n"
            f"Their red lines:\n{red_lines}\n\n"
            f"WIN THEMES this section must carry:\n{theme_block}\n\n"
            f"SOURCE MATERIAL (cite these ids inline as [ID]):\n{context}\n\n"
            f"HOW TO USE THE SOURCES: {instruction}\n\n"
            "RULES\n"
            "- Write for the buyer, about the buyer's outcome. Never open with 'We are'.\n"
            "- Every factual claim must trace to the source material above. If the "
            "sources do not support a claim, leave it out rather than asserting it.\n"
            "- Cite source ids inline in square brackets where a claim comes from one.\n"
            "- No absolute guarantees, no unbounded commitments, no '100%' promises.\n"
            "- Markdown. Start with '## " + section.title + "'. No preamble, no "
            "closing commentary about what you wrote.\n"
        )
        if failure_reason:
            prompt += (
                f"\nTHIS SECTION FAILED REVIEW AND IS BEING REDRAFTED.\n"
                f"Reason: {failure_reason}\n"
                f"Fix that specific problem while keeping everything else intact.\n"
            )
        return prompt

    @staticmethod
    def _format_context(pack: ContextPack, budget: int = MAX_CONTEXT_CHARS) -> str:
        out: list[str] = []
        remaining = budget
        for candidate in pack.candidates:
            snippet = candidate.text[: max(0, min(MAX_CANDIDATE_CHARS, remaining))]
            if not snippet:
                break
            out.append(f"[{candidate.chunk_id}] ({candidate.source_ref})\n{snippet}")
            remaining -= len(snippet)
        return "\n\n".join(out) or "(no source material retrieved)"

    @staticmethod
    def _clean(text: str, title: str) -> str:
        """Strip fences and any preamble before the heading."""
        body = text.strip()
        if body.startswith("```"):
            lines = [ln for ln in body.splitlines() if not ln.strip().startswith("```")]
            body = "\n".join(lines).strip()
        index = body.find("## ")
        if index > 0:
            body = body[index:]
        if not body.startswith("## "):
            body = f"## {title}\n\n{body}"
        return body.strip() + "\n"

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider


_DECISION_INSTRUCTION: dict[ReuseDecision, str] = {
    ReuseDecision.REUSE: (
        "The top source answers this almost exactly. Reuse its substance closely, "
        "changing only what is needed to fit this buyer. Do not embellish it."
    ),
    ReuseDecision.ADAPT: (
        "The top source is close but not exact. Rework it for this buyer's context, "
        "keeping its facts intact and dropping anything that does not apply."
    ),
    ReuseDecision.SYNTHESIZE: (
        "No single source answers this. Combine the sources into a coherent answer, "
        "and say less rather than inventing what they do not cover."
    ),
    ReuseDecision.STAKEHOLDER: (
        "The sources do not support an answer. Write only what they support and state "
        "plainly where input is required."
    ),
}
