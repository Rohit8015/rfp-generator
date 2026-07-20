"""A7 Proof Point Matcher — Phase 6.

In: requirements + proof library. Out: per-requirement STRONG / PARTIAL / GAP with
source IDs.

Hard rule (CLAUDE.md): GAPs are surfaced, never invented around. A GAP requirement
produces a stakeholder brief, not prose. The ProofMatch contract already makes "GAP with
a proof cited" impossible to construct, so this module cannot violate the rule even by
accident -- it can only be wrong about which bucket a requirement falls in.

DETERMINISTIC: no model call. Asking a model "does this proof support this requirement?"
gets a yes far too often, and the asymmetry matters here: a false GAP costs a human
glance, a false STRONG puts an unevidenced claim in front of a client.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.models.schemas import Fit, ProofMatch, ProofPoint, Requirement

#: Similarity floors. Deliberately conservative, for the asymmetry described above.
STRONG_FLOOR = 0.28
PARTIAL_FLOOR = 0.12
#: A proof the library itself marks weak cannot carry a requirement to STRONG.
LIBRARY_STRENGTH_RANK = {"STRONG": 2, "MEDIUM": 1, "MODERATE": 1, "WEAK": 0}
MAX_SUPPORTING = 3

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

    def __init__(self, proofs: list[ProofPoint] | None = None, settings=None) -> None:
        self.settings = settings
        self._proofs = proofs

    # --- public ---------------------------------------------------------------------

    def match(self, requirements: list[Requirement]) -> list[ProofMatch]:
        proofs = self.proofs
        return [self._match_one(r, proofs) for r in requirements]

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

    def _match_one(self, requirement: Requirement, proofs: list[ProofPoint]) -> ProofMatch:
        scored = sorted(
            ((self._score(requirement, p), p) for p in proofs), key=lambda t: -t[0]
        )
        if not scored or scored[0][0] < PARTIAL_FLOOR:
            return ProofMatch(
                requirement_id=requirement.id,
                fit=Fit.GAP,
                rationale="no proof point in the library addresses this requirement",
            )

        best_score, best_proof = scored[0]
        supporting = [p.id for score, p in scored if score >= PARTIAL_FLOOR][:MAX_SUPPORTING]

        if best_score >= STRONG_FLOOR and self._library_strength(best_proof) >= 2:
            return ProofMatch(
                requirement_id=requirement.id,
                fit=Fit.STRONG,
                proof_ids=supporting,
                rationale=(f"{best_proof.id} directly evidences this "
                           f"(overlap {best_score:.2f}, library strength STRONG)"),
            )
        return ProofMatch(
            requirement_id=requirement.id,
            fit=Fit.PARTIAL,
            proof_ids=supporting,
            rationale=(f"{best_proof.id} is adjacent but not direct evidence "
                       f"(overlap {best_score:.2f})"),
        )

    @staticmethod
    def _library_strength(proof: ProofPoint) -> int:
        for tag in proof.tags:
            rank = LIBRARY_STRENGTH_RANK.get(str(tag).upper())
            if rank is not None:
                return rank
        return 1

    @staticmethod
    def _score(requirement: Requirement, proof: ProofPoint) -> float:
        """Content-token overlap, with the proof's curated tags weighted up.

        Tags are hand-picked keywords, so a tag hit is better evidence of topical match
        than an incidental word shared with the prose.
        """
        req_tokens = _tokens(requirement.text)
        if not req_tokens:
            return 0.0

        proof_tokens = _tokens(proof.text)
        tag_tokens = _tokens(" ".join(proof.tags).replace("-", " "))

        union = req_tokens | proof_tokens
        prose_overlap = len(req_tokens & proof_tokens) / len(union) if union else 0.0
        tag_overlap = len(req_tokens & tag_tokens) / len(req_tokens) if tag_tokens else 0.0
        return round(0.55 * prose_overlap + 0.45 * tag_overlap, 4)


def gap_requirement_ids(matches: list[ProofMatch]) -> list[str]:
    """The GAP list a human must see. Never silently absorbed."""
    return [m.requirement_id for m in matches if m.fit is Fit.GAP]
