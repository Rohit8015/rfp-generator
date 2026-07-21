"""A7 Proof Point Matcher — Phase 6.

In: requirements + proof library. Out: per-requirement STRONG / PARTIAL / GAP with
source IDs.

Hard rule (CLAUDE.md): GAPs are surfaced, never invented around. A GAP requirement
produces a stakeholder brief, not prose. The ProofMatch contract already makes "GAP with
a proof cited" impossible to construct, so this module cannot violate the rule even by
accident -- it can only be wrong about which bucket a requirement falls in.

NO GENERATIVE CALL. Asking a model "does this proof support this requirement?" gets a
yes far too often, and the asymmetry matters here: a false GAP costs a human glance, a
false STRONG puts an unevidenced claim in front of a client.

Matching does use the LOCAL embedding model, which is a measurement rather than a
judgement and has no such bias. This was not the first design. Pure lexical overlap
marked 80% of RFP-A's requirements as GAP, because requirements and proof claims say the
same thing in different words -- a requirement asks for "customer onboarding with KYC
and Aadhaar eSign" while the proof claims "digital lending, TAT reduced from 3 days to
15 minutes". Those are the same capability with almost no shared vocabulary, which is
precisely what an embedding resolves and a keyword cannot.

Lexical overlap is kept as a secondary signal, because the library's curated tags are
high-precision when they do hit. With no provider available the matcher degrades to
lexical only and says so.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.models.schemas import Fit, ProofMatch, ProofPoint, Requirement

log = logging.getLogger(__name__)

# Two scoring scales, because two matchers.
#
# Cross-encoder relevance logits (ms-marco-MiniLM). Measured on RFP-A against the
# 20-proof library: requirements the library genuinely covers score -4.9 to -8.1, and
# ones it plainly does not (multilingual UI -10.3, gamification -11.2, social listening
# -11.3, AR/VR -11.4) sit clearly below. The boundary is placed in the gap between those
# clusters, nearer the uncovered side, because a false STRONG costs more than a false GAP.
#
# Swept against RFP-A. At -10.5 the multilingual requirement starts being called
# PARTIAL, which is wrong: the library has no vernacular-UI proof at all. At -10.0 every
# known-uncovered requirement is still correctly a GAP while 47% rather than 57% of
# requirements are called gaps, so -10.0 is the loosest defensible boundary.
CE_PARTIAL_FLOOR = -10.0
CE_STRONG_FLOOR = -6.5

# Lexical containment, used only when no reranker is available. Separate scale entirely.
LEXICAL_PARTIAL_FLOOR = 0.12
LEXICAL_STRONG_FLOOR = 0.28
#: A proof the library itself marks weak cannot carry a requirement to STRONG.
LIBRARY_STRENGTH_RANK = {"STRONG": 2, "MEDIUM": 1, "MODERATE": 1, "WEAK": 0}
MAX_SUPPORTING = 3
#: Minimum content words a requirement and a proof must share, whatever the ratio says.
#: Containment is unstable on short requirements: a five-word requirement sharing one
#: incidental word scores 0.20, which was enough to call an alpaca-supply requirement
#: PARTIAL. One shared word is coincidence; two is a topic.
MIN_SHARED_TOKENS = 2

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "with", "in", "on", "by", "is", "are",
    "be", "as", "at", "or", "that", "this", "it", "its", "from", "vendor", "supplier",
    "bidder", "shall", "must", "should", "may", "will", "provide", "include", "our",
    "we", "you", "your", "system", "solution", "support", "using", "based",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


class ProofMatcher:
    """Matches requirements to proof points. One public method: match()."""

    def __init__(self, proofs: list[ProofPoint] | None = None, settings=None,
                 provider=None, use_embeddings: bool = True) -> None:
        self.settings = settings
        self._proofs = proofs
        self._provider = provider
        self.use_embeddings = use_embeddings

    # --- public ---------------------------------------------------------------------

    def match(self, requirements: list[Requirement]) -> list[ProofMatch]:
        proofs = self.proofs
        semantic = self._semantic_scores(requirements, proofs)
        return [
            self._match_one(r, proofs, semantic[i] if semantic else None)
            for i, r in enumerate(requirements)
        ]

    def _semantic_scores(self, requirements: list[Requirement],
                         proofs: list[ProofPoint]) -> list[list[float]] | None:
        """Cross-encoder relevance of every proof against every requirement.

        The cross-encoder, not the bi-encoder. Cosine similarity between separately
        embedded texts measures topical proximity, and on this corpus everything is
        proximate: a proof about gamification scored as high against a fraud-detection
        requirement as the fraud case study did, because both are fintech. Neither an
        absolute nor a relative cut separated them.

        A cross-encoder reads the pair together and scores relevance directly, which is
        the question actually being asked. It costs more compute, but the library is 20
        proofs and this runs once per bid.
        """
        if not self.use_embeddings or not requirements or not proofs:
            return None
        documents = [f"{p.title}. {p.text}" for p in proofs]
        try:
            provider = self._get_provider()
            scores: list[list[float]] = []
            for requirement in requirements:
                ranked = provider.rerank(requirement.text, documents)
                row = [0.0] * len(documents)
                for index, score in ranked:
                    row[index] = float(score)
                scores.append(row)
            return scores
        except Exception as exc:  # noqa: BLE001 - degrade to lexical, and say so
            log.info("no reranker; proof matching is lexical only: %s", exc)
            return None

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider

    # --- library --------------------------------------------------------------------

    @property
    def proofs(self) -> list[ProofPoint]:
        if self._proofs is None:
            self._proofs = self.load_library(self.settings)
        return self._proofs

    @staticmethod
    def load_library(settings=None) -> list[ProofPoint]:
        """Read the proof library into contracts."""
        if settings is None:
            from config import get_settings

            settings = get_settings()
        path = Path(settings.data_path) / "proof_library" / "proof_points.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        records = (next(v for v in obj.values() if isinstance(v, list))
                   if isinstance(obj, dict) else obj)
        return [
            ProofPoint(
                id=r["id"],
                title=r.get("claim", "")[:120],
                text=f"{r.get('claim', '')}\n\n{r.get('evidence', '')}".strip(),
                source_ref=r.get("verifiable_source", ""),
                tags=[*r.get("covers_tags", []), str(r.get("strength", ""))],
            )
            for r in records
        ]

    # --- internals ------------------------------------------------------------------

    def _match_one(self, requirement: Requirement, proofs: list[ProofPoint],
                   semantic: list[float] | None = None) -> ProofMatch:
        if semantic is not None:
            # Cross-encoder relevance decides; lexical overlap is not mixed in, because
            # blending an unbounded logit with a 0-1 ratio would be a units error.
            candidates = [(round(semantic[i], 4), p) for i, p in enumerate(proofs)]
        else:
            candidates = [
                (self._score(requirement, p), p) for p in proofs
                if self._shared_tokens(requirement, p) >= MIN_SHARED_TOKENS
            ]

        partial_floor = CE_PARTIAL_FLOOR if semantic is not None else LEXICAL_PARTIAL_FLOOR
        strong_floor = CE_STRONG_FLOOR if semantic is not None else LEXICAL_STRONG_FLOOR
        scale = "relevance" if semantic is not None else "overlap"

        scored = sorted(candidates, key=lambda t: -t[0])
        if not scored or scored[0][0] < partial_floor:
            best = f" (best {scored[0][1].id} at {scored[0][0]:.2f})" if scored else ""
            return self._gap(
                requirement,
                f"no proof point in the library addresses this requirement{best}",
            )

        best_score, best_proof = scored[0]
        supporting = [p.id for score, p in scored
                      if score >= partial_floor][:MAX_SUPPORTING]

        if best_score >= strong_floor and self._library_strength(best_proof) >= 2:
            return ProofMatch(
                requirement_id=requirement.id,
                fit=Fit.STRONG,
                proof_ids=supporting,
                rationale=(f"{best_proof.id} directly evidences this "
                           f"({scale} {best_score:.2f}, library strength STRONG)"),
            )
        return ProofMatch(
            requirement_id=requirement.id,
            fit=Fit.PARTIAL,
            proof_ids=supporting,
            rationale=(f"{best_proof.id} is adjacent but not direct evidence "
                       f"({scale} {best_score:.2f})"),
        )

    @staticmethod
    def _gap(requirement: Requirement, rationale: str) -> ProofMatch:
        return ProofMatch(requirement_id=requirement.id, fit=Fit.GAP, rationale=rationale)

    @staticmethod
    def _library_strength(proof: ProofPoint) -> int:
        for tag in proof.tags:
            rank = LIBRARY_STRENGTH_RANK.get(str(tag).upper())
            if rank is not None:
                return rank
        return 1

    @staticmethod
    def _shared_tokens(requirement: Requirement, proof: ProofPoint) -> int:
        """Content words the requirement and the proof have in common."""
        req_tokens = _tokens(requirement.text)
        proof_tokens = _tokens(proof.text) | _tokens(" ".join(proof.tags).replace("-", " "))
        return len(req_tokens & proof_tokens)

    @staticmethod
    def _score(requirement: Requirement, proof: ProofPoint) -> float:
        """How much of the requirement's subject the proof covers.

        Containment, not Jaccard. The question is "does this proof speak to what the
        requirement asks", and Jaccard answers a different one -- it divides by the union,
        so a long, detailed case study scores worse than a thin one purely for being
        longer. The first version of this scorer used Jaccard and marked 82% of
        requirements as GAP.

        Tags are hand-picked keywords, so a tag hit is better evidence of topical match
        than an incidental word shared with the prose.
        """
        req_tokens = _tokens(requirement.text)
        if not req_tokens:
            return 0.0

        proof_tokens = _tokens(proof.text)
        tag_tokens = _tokens(" ".join(proof.tags).replace("-", " "))

        prose_overlap = len(req_tokens & proof_tokens) / len(req_tokens)
        tag_overlap = len(req_tokens & tag_tokens) / len(req_tokens) if tag_tokens else 0.0
        return round(0.6 * prose_overlap + 0.4 * tag_overlap, 4)


def gap_requirement_ids(matches: list[ProofMatch]) -> list[str]:
    """The GAP list a human must see. Never silently absorbed."""
    return [m.requirement_id for m in matches if m.fit is Fit.GAP]
