"""A5 Win Theme Generator — Phase 6.

In: BuyerProfile + differentiator library (the proof points). Out: 3-5 WinTheme objects.
Themes are buyer-side, not seller-side. A theme threading fewer than two requirements is
decorative and is dropped with a logged reason.

Division of labour: the model writes the theme statement, because phrasing a benefit in
the buyer's language is a writing task. Everything checkable is then verified in Python
-- which requirements a theme actually threads, which proofs actually support it, and
whether it survives the two-requirement rule. A model asked to self-report its own
coverage will overstate it, and that coverage is precisely the test the rule applies.

The WinTheme contract refuses to construct a surviving theme with fewer than two
requirements or no proof, so the rule cannot be bypassed downstream.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from src.models.schemas import BuyerProfile, ProofPoint, Requirement, WinTheme

log = logging.getLogger(__name__)

MIN_REQUIREMENTS_PER_THEME = 2
MAX_THEMES = 5
#: How strongly a requirement must relate to a theme to count as threaded.
THREAD_FLOOR = 0.10

#: Seller-side phrasing. A theme about us rather than about the buyer is decorative.
_SELLER_SIDE = re.compile(
    r"\b(we are|we're|our company is|c4 is|industry[- ]leading|world[- ]class|"
    r"best[- ]in[- ]class|market leader|leading provider|award[- ]winning|"
    r"trusted partner|we offer|we provide)\b",
    re.I,
)

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "with", "in", "on", "by", "is", "are",
    "be", "as", "at", "or", "that", "this", "it", "its", "from", "your", "you", "our",
    "we", "will", "can", "shall", "must", "should", "may", "vendor", "supplier",
    "bidder", "provide", "include", "system", "solution", "platform",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in _STOP and len(w) > 2}


class _ThemeDraft(BaseModel):
    statement: str = Field(min_length=15)
    buyer_pain_addressed: str = ""


class _ThemeBatch(BaseModel):
    themes: list[_ThemeDraft] = Field(default_factory=list)


class WinThemeGenerator:
    """Produces win themes. One public method: generate()."""

    def __init__(self, provider=None, use_llm: bool = True) -> None:
        self._provider = provider
        self.use_llm = use_llm

    # --- public ---------------------------------------------------------------------

    def generate(
        self,
        buyer: BuyerProfile,
        requirements: list[Requirement],
        proofs: list[ProofPoint],
    ) -> list[WinTheme]:
        """Return themes, surviving and dropped. Dropped ones keep their reason."""
        drafts = self._draft(buyer, proofs) if self.use_llm else []
        if not drafts:
            drafts = self._fallback_drafts(buyer)

        themes: list[WinTheme] = []
        for index, draft in enumerate(drafts[:MAX_THEMES + 3], start=1):
            themes.append(self._verify(f"T-{index:02d}", draft, requirements, proofs))

        surviving = [t for t in themes if not t.dropped]
        # Keep the strongest few; the plan wants 3-5, not a list of everything tried.
        surviving.sort(key=lambda t: -len(t.requirement_ids_covered))
        keep = {t.id for t in surviving[:MAX_THEMES]}
        for theme in themes:
            if not theme.dropped and theme.id not in keep:
                theme.dropped = True
                theme.drop_reason = "weaker than the top themes; dropped to keep 3-5"
        return themes

    @staticmethod
    def surviving(themes: list[WinTheme]) -> list[WinTheme]:
        return [t for t in themes if not t.dropped]

    # --- drafting -------------------------------------------------------------------

    def _draft(self, buyer: BuyerProfile, proofs: list[ProofPoint]) -> list[_ThemeDraft]:
        try:
            provider = self._get_provider()
        except Exception as exc:  # noqa: BLE001 - offline is supported
            log.info("no provider; using deterministic theme drafts: %s", exc)
            return []

        pains = "\n".join(f"- {p}" for p in buyer.stated_pains[:6]) or "- not stated"
        criteria = "\n".join(
            f"- {c.name}" + (f" (weight {c.weight})" if c.weight else "")
            for c in buyer.evaluation_criteria[:8]
        ) or "- not disclosed"
        evidence = "\n".join(f"- {p.id}: {p.title}" for p in proofs[:12])

        prompt = (
            "Write 5 to 7 candidate win themes for a proposal.\n\n"
            "A win theme states a benefit the BUYER receives, in the buyer's language. "
            "It is never a statement about the bidder.\n"
            "  Good: 'your operations team cuts cost-to-serve without changing headcount'\n"
            "  Bad:  'we are a leading provider of digital transformation'\n\n"
            "Rules:\n"
            "- Address the buyer's stated pains and their evaluation criteria.\n"
            "- Each theme must be specific enough to be provable, not a slogan.\n"
            "- Never begin with 'we'.\n"
            "- One sentence each.\n\n"
            f"Buyer pains:\n{pains}\n\n"
            f"Evaluation criteria:\n{criteria}\n\n"
            f"Evidence available:\n{evidence}\n\n"
            'Return JSON: {"themes": [{"statement": "...", '
            '"buyer_pain_addressed": "..."}]}'
        )
        try:
            resp = provider.generate(prompt, tier="strong", schema=_ThemeBatch)
        except Exception as exc:  # noqa: BLE001 - never fail on a model fault
            log.warning("theme drafting failed; using deterministic drafts: %s", exc)
            return []
        return list(resp.parsed.themes) if resp.parsed else []

    @staticmethod
    def _fallback_drafts(buyer: BuyerProfile) -> list[_ThemeDraft]:
        """Offline path: build themes from the buyer's own disclosed priorities."""
        drafts: list[_ThemeDraft] = []
        for criterion in buyer.evaluation_criteria[:MAX_THEMES]:
            drafts.append(_ThemeDraft(
                statement=(f"your evaluation of {criterion.name.lower()} is met with "
                           f"evidence rather than assertion"),
                buyer_pain_addressed=criterion.name,
            ))
        for pain in buyer.stated_pains[:3]:
            drafts.append(_ThemeDraft(
                statement=f"your team addresses {pain.lower()[:90]} without added burden",
                buyer_pain_addressed=pain,
            ))
        return drafts

    # --- verification ---------------------------------------------------------------

    def _verify(self, theme_id: str, draft: _ThemeDraft,
                requirements: list[Requirement], proofs: list[ProofPoint]) -> WinTheme:
        """Measure what the theme actually threads. Never trust it to self-report."""
        statement = re.sub(r"\s+", " ", draft.statement).strip()

        if _SELLER_SIDE.search(statement):
            return WinTheme(
                id=theme_id, statement=statement,
                buyer_pain_addressed=draft.buyer_pain_addressed,
                dropped=True,
                drop_reason="seller-side phrasing: describes the bidder, not the buyer",
            )

        theme_tokens = _tokens(statement) | _tokens(draft.buyer_pain_addressed)
        if not theme_tokens:
            return WinTheme(
                id=theme_id, statement=statement or "(empty)",
                buyer_pain_addressed=draft.buyer_pain_addressed,
                dropped=True, drop_reason="no content words to thread against",
            )

        threaded = [
            r.id for r in requirements
            if self._overlap(theme_tokens, _tokens(r.text)) >= THREAD_FLOOR
        ]
        supporting = [
            p.id for p in proofs
            if self._overlap(theme_tokens, _tokens(p.text) | _tokens(" ".join(p.tags)))
            >= THREAD_FLOOR
        ][:4]

        if len(threaded) < MIN_REQUIREMENTS_PER_THEME:
            return WinTheme(
                id=theme_id, statement=statement,
                buyer_pain_addressed=draft.buyer_pain_addressed,
                requirement_ids_covered=threaded, proof_ids=supporting,
                dropped=True,
                drop_reason=(f"threads {len(threaded)} requirement(s), fewer than the "
                             f"{MIN_REQUIREMENTS_PER_THEME} required: decorative"),
            )
        if not supporting:
            return WinTheme(
                id=theme_id, statement=statement,
                buyer_pain_addressed=draft.buyer_pain_addressed,
                requirement_ids_covered=threaded,
                dropped=True,
                drop_reason="no proof point supports this theme: unevidenced claim",
            )

        return WinTheme(
            id=theme_id,
            statement=statement,
            buyer_pain_addressed=draft.buyer_pain_addressed or "unstated",
            requirement_ids_covered=threaded,
            proof_ids=supporting,
        )

    @staticmethod
    def _overlap(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a)

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider
