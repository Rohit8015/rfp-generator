"""A3 Buyer Intelligence — Phase 4.

In: DocumentTree. Out: BuyerProfile (audience, pains, decision constraints, evaluation
criteria and weights, red lines, tone register, submission rules).

This object is passed into every downstream generation prompt, which makes it the
highest-leverage object in the system and the one least tolerable to hallucinate. So the
split of work is deliberate:

- Anything the document states literally is parsed deterministically. Evaluation weights
  in particular: a fabricated weight would misdirect every section's emphasis, and
  weights are always tabulated, so a model is the wrong tool.
- Only the interpretive fields go to a model -- audience roles, the pains behind the
  requirements, tone register. These are judgements, and a wrong one costs emphasis
  rather than correctness.
- The deterministic pass always wins a conflict. The model can add, never overwrite.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from src.models.schemas import BuyerProfile, DocumentTree, EvalCriterion
from src.utils import docparse

log = logging.getLogger(__name__)

#: "| Technical Solution | 35% | Workshop presentation |"
_TABLE_ROW = re.compile(r"^\s*\|(?P<cells>.+)\|\s*$", re.MULTILINE)
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_POINTS = re.compile(r"\b(\d{1,3})\s*(?:points?|pts?|marks?)\b", re.I)

_EVAL_SECTION = re.compile(r"evaluation|scoring|award|weighting|criteria", re.I)
_SUBMISSION_SECTION = re.compile(
    r"submission|how to submit|instructions to bidders|proposal format", re.I
)

#: Language that disqualifies a bid outright if breached.
_RED_LINE = re.compile(
    r"\b(disqualif\w*|non[- ]?compliant|will be rejected|shall not be considered|"
    r"mandatory pass|pass/fail|must pass|failure to comply|automatic rejection)\b",
    re.I,
)
#: Hard commercial or regulatory limits the response must respect.
_CONSTRAINT = re.compile(
    r"\b(budget|ceiling|not to exceed|cap(?:ped)?|deadline|by \d{1,2} \w+|"
    r"availability|uptime|sla|penalt\w*|compl\w+ with|guidelines?|regulat\w+|"
    r"act\b|bill\b|gdpr|rbi|dpdp|iso ?\d+|soc ?2)\b",
    re.I,
)


class _Interpretation(BaseModel):
    """The judgement-shaped fields. Everything factual is parsed, not generated."""

    audience_roles: list[str] = Field(default_factory=list)
    stated_pains: list[str] = Field(default_factory=list)
    tone_register: str = "professional"


class BuyerIntelligence:
    """Builds a BuyerProfile from a parsed RFP. One public method: profile()."""

    def __init__(self, provider=None, use_llm: bool = True) -> None:
        self._provider = provider
        self.use_llm = use_llm

    # --- public ---------------------------------------------------------------------

    def profile(self, tree: DocumentTree) -> BuyerProfile:
        criteria = self._evaluation_criteria(tree)
        profile = BuyerProfile(
            audience_roles=self._audience_from_text(tree),
            stated_pains=[],
            decision_constraints=self._constraints(tree),
            evaluation_criteria=criteria,
            red_lines=self._red_lines(tree),
            tone_register="professional",
            submission_rules=self._submission_rules(tree),
        )
        if self.use_llm:
            self._enrich(tree, profile)
        return profile

    # --- deterministic passes -------------------------------------------------------

    def _evaluation_criteria(self, tree: DocumentTree) -> list[EvalCriterion]:
        """Pull criteria and weights from tables. Never generated."""
        out: list[EvalCriterion] = []
        seen: set[str] = set()

        for node in tree.nodes():
            in_eval_section = bool(_EVAL_SECTION.search(node.title or ""))
            for m in _TABLE_ROW.finditer(node.text):
                cells = [docparse.normalize(c) for c in m.group("cells").split("|")]
                cells = [c for c in cells if c and not set(c) <= {"-", ":", " "}]
                if len(cells) < 2:
                    continue
                name = cells[0]
                if not name or name.lower() in {"criterion", "criteria", "requirement"}:
                    continue

                weight = None
                for cell in cells[1:]:
                    pm = _PERCENT.search(cell) or _POINTS.search(cell)
                    if pm:
                        weight = float(pm.group(1))
                        break
                # Outside an evaluation section, only weighted rows are criteria --
                # otherwise every table in the document becomes scoring criteria.
                if weight is None and not in_eval_section:
                    continue
                if re.fullmatch(r"[A-Z]{1,4}-\d{1,4}", name):
                    continue  # a numbered requirement, not a criterion
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(EvalCriterion(name=name, weight=weight))
        return out

    def _submission_rules(self, tree: DocumentTree) -> list[str]:
        rules: list[str] = []
        for node in tree.nodes():
            if not _SUBMISSION_SECTION.search(node.title or ""):
                continue
            for sentence in docparse.split_sentences(node.text):
                if len(sentence.split()) >= 4:
                    rules.append(sentence)
        return self._dedupe(rules)

    def _constraints(self, tree: DocumentTree) -> list[str]:
        found: list[str] = []
        for node in tree.nodes():
            for sentence in docparse.split_sentences(node.text):
                if len(sentence.split()) < 4:
                    continue
                if _CONSTRAINT.search(sentence):
                    found.append(sentence)
        return self._dedupe(found)

    def _red_lines(self, tree: DocumentTree) -> list[str]:
        found: list[str] = []
        for node in tree.nodes():
            for sentence in docparse.split_sentences(node.text):
                if _RED_LINE.search(sentence) and len(sentence.split()) >= 3:
                    found.append(sentence)
        return self._dedupe(found)

    @staticmethod
    def _audience_from_text(tree: DocumentTree) -> list[str]:
        """Named roles and the issuing organisation, taken literally from the text."""
        # Normalize first: the issuer line is usually emphasised ("**Issued By:**"),
        # and matching raw markdown misses it.
        blob = docparse.normalize(" ".join(n.text for n in tree.nodes()))
        roles: list[str] = []

        issuer = re.search(
            r"(?:issued by|issuing (?:authority|organisation|organization)|client)"
            r"\s*[:\-]*\s*([A-Z][\w&.,' ]{3,60})",
            blob, re.I,
        )
        if issuer:
            roles.append(issuer.group(1).strip(" .,"))

        for role in re.findall(
            r"\b(chief \w+ officer|CIO|CTO|CFO|CEO|COO|CISO|"
            r"head of [\w ]{3,30}|group head|programme director|project director|"
            r"procurement (?:head|manager|team)|evaluation committee|"
            r"expert review committee|steering committee|board)\b",
            blob, re.I,
        ):
            cleaned = re.sub(r"\s+", " ", role).strip()
            if cleaned.lower() not in {r.lower() for r in roles}:
                roles.append(cleaned)
        return roles[:12]

    @staticmethod
    def _dedupe(items: list[str], limit: int = 25) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = re.sub(r"[^a-z0-9 ]", "", item.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out[:limit]

    # --- interpretive pass ----------------------------------------------------------

    def _enrich(self, tree: DocumentTree, profile: BuyerProfile) -> None:
        """Add audience roles, pains and tone. Never overwrites parsed facts."""
        try:
            provider = self._get_provider()
        except Exception as exc:  # noqa: BLE001 - offline is supported
            log.info("no provider; buyer profile stays deterministic: %s", exc)
            return

        body = "\n\n".join(
            f"## {n.title or n.id}\n{n.text[:900]}" for n in tree.nodes() if n.text.strip()
        )[:9000]

        prompt = (
            "Read this request for proposal and infer the buyer's situation.\n\n"
            "Return JSON with three keys:\n"
            '  "audience_roles": who will read and score this response, by role\n'
            '  "stated_pains": the business problems driving this procurement, in the '
            "buyer's own terms, one sentence each\n"
            '  "tone_register": one of formal, professional, technical, consultative\n\n'
            "Rules:\n"
            "- Ground every pain in something the document actually says. Do not invent "
            "problems that would merely be convenient to solve.\n"
            "- Roles only, not company names.\n"
            "- At most six pains.\n\n"
            f"{body}"
        )

        try:
            resp = provider.generate(prompt, tier="strong", schema=_Interpretation)
        except Exception as exc:  # noqa: BLE001 - never fail a profile on a model fault
            log.warning("buyer profile enrichment failed: %s", exc)
            return

        result = resp.parsed
        if result is None:
            return

        known = {r.lower() for r in profile.audience_roles}
        for role in result.audience_roles:
            role = docparse.normalize(role)
            if role and role.lower() not in known:
                known.add(role.lower())
                profile.audience_roles.append(role)

        profile.stated_pains = [
            docparse.normalize(p) for p in result.stated_pains if p.strip()
        ][:6]
        if result.tone_register.strip():
            profile.tone_register = result.tone_register.strip().lower()

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider
