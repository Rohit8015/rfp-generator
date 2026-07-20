"""A8 Hybrid Retriever — Phase 5.

BM25 + dense -> Reciprocal Rank Fusion -> cross-encoder rerank of top-30.
Query expansion: original text + requirement paraphrase + section purpose.
Out: ContextPack, a list of scored attributed candidates. reuse_decision comes from
the calibrated thresholds; confidence is the normalized rank-1/rank-2 margin.

Why RRF rather than score blending: BM25 scores are unbounded and corpus-dependent while
cosine similarities sit in a narrow band, so any weighted sum of the two is really a
weighted sum of their scales. RRF combines ranks, which are directly comparable, and
needs no per-corpus tuning.

The reuse decision is taken from the raw dense similarity of the best candidate, not
from the rerank or RRF score. Calibration measured a dense similarity distribution, so
only a dense similarity can be compared against those thresholds. Feeding a rerank score
into a dense-calibrated threshold would be a units error.
"""

from __future__ import annotations

import logging
import re

from src.models.schemas import ContextPack, ReuseDecision, RetrievedCandidate

log = logging.getLogger(__name__)

#: RRF damping. 60 is the value from the original paper and is not corpus-sensitive.
RRF_K = 60
#: How many fused candidates the cross-encoder sees. The plan specifies 30.
RERANK_DEPTH = 30
DEFAULT_TOP_K = 5

_STOPWORDS = {
    "what", "which", "how", "does", "do", "your", "you", "the", "a", "an", "of", "to",
    "for", "and", "with", "in", "on", "is", "are", "describe", "explain", "provide",
    "please", "can", "we", "our", "us",
}


class HybridRetriever:
    """Retrieves a scored context pack for a query. One public method: retrieve()."""

    def __init__(self, settings=None, provider=None, thresholds=None) -> None:
        from config import get_settings

        self.settings = settings or get_settings()
        self._provider = provider
        self._thresholds = thresholds
        self._bm25 = None
        self._chunks = None
        self._collection = None

    # --- public ---------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        *,
        paraphrase: str | None = None,
        section_purpose: str | None = None,
        dense_only: bool = False,
        rerank: bool = True,
    ) -> ContextPack:
        """Return a ContextPack of scored, attributed candidates.

        `dense_only` exists so the hybrid pipeline can be measured against the dense
        baseline it claims to beat, using exactly the same code path.
        """
        expansions = self._expand(query, paraphrase, section_purpose)
        joined = " ".join([query, *expansions])

        dense = self._dense_ranking(query)
        if dense_only:
            fused_ids = [cid for cid, _ in dense]
        else:
            lexical = self._bm25_ranking(joined)
            fused_ids = self._rrf([cid for cid, _ in dense], [cid for cid, _ in lexical])

        dense_scores = dict(dense)
        shortlist = fused_ids[:RERANK_DEPTH]

        rerank_scores: dict[str, float] = {}
        if rerank and shortlist:
            rerank_scores = self._rerank(query, shortlist)
            shortlist = sorted(shortlist, key=lambda c: -rerank_scores.get(c, 0.0))

        candidates = self._to_candidates(shortlist[:top_k], dense_scores, rerank_scores,
                                         fused_ids)
        decision, confidence = self._decide(candidates, dense_scores)

        return ContextPack(
            query=query,
            expanded_queries=expansions,
            candidates=candidates,
            reuse_decision=decision,
            confidence=confidence,
            calibration_version=(
                None if decision is ReuseDecision.STAKEHOLDER
                else self.thresholds.version
            ),
        )

    # --- lazy resources -------------------------------------------------------------

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider

    @property
    def thresholds(self):
        if self._thresholds is None:
            from src.ingestion.calibrate import load_thresholds

            self._thresholds = load_thresholds(self.settings)
        return self._thresholds

    @property
    def chunks(self):
        self._load_lexical()
        return self._chunks

    def _load_lexical(self) -> None:
        if self._bm25 is None:
            from src.ingestion.ingest import load_bm25

            self._bm25, self._chunks = load_bm25(self.settings)

    @property
    def collection(self):
        if self._collection is None:
            import chromadb

            from src.ingestion.ingest import COLLECTION

            client = chromadb.PersistentClient(path=str(self.settings.chroma_path))
            self._collection = client.get_collection(COLLECTION)
        return self._collection

    # --- retrieval stages -----------------------------------------------------------

    @staticmethod
    def _expand(query: str, paraphrase: str | None, purpose: str | None) -> list[str]:
        """Original text + requirement paraphrase + section purpose.

        The fallback paraphrase is a keyword reduction rather than a generated one: it
        costs no model call, and its job is to help BM25, which wants terms not prose.
        """
        out: list[str] = []
        if paraphrase and paraphrase.strip():
            out.append(paraphrase.strip())
        else:
            terms = [w for w in re.findall(r"[A-Za-z0-9][\w./-]*", query.lower())
                     if w not in _STOPWORDS and len(w) > 2]
            if terms:
                out.append(" ".join(dict.fromkeys(terms)))
        if purpose and purpose.strip():
            out.append(purpose.strip())
        return out

    def _dense_ranking(self, query: str) -> list[tuple[str, float]]:
        vector = self.provider.embed([query])[0]
        n = min(RERANK_DEPTH * 2, max(1, self.collection.count()))
        res = self.collection.query(query_embeddings=[vector], n_results=n)
        ids = res["ids"][0]
        # Chroma returns cosine distance; similarity is 1 - distance.
        sims = [1.0 - d for d in res["distances"][0]]
        return list(zip(ids, sims))

    def _bm25_ranking(self, text: str) -> list[tuple[str, float]]:
        from src.ingestion.ingest import tokenize

        self._load_lexical()
        scores = self._bm25.get_scores(tokenize(text))
        ranked = sorted(zip((c.id for c in self._chunks), scores), key=lambda t: -t[1])
        return [r for r in ranked if r[1] > 0][: RERANK_DEPTH * 2]

    @staticmethod
    def _rrf(*rankings: list[str]) -> list[str]:
        """Reciprocal Rank Fusion over rank positions, not scores."""
        fused: dict[str, float] = {}
        for ranking in rankings:
            for position, chunk_id in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)
        return [cid for cid, _ in sorted(fused.items(), key=lambda t: -t[1])]

    def _rerank(self, query: str, chunk_ids: list[str]) -> dict[str, float]:
        by_id = {c.id: c for c in self.chunks}
        docs = [by_id[cid].text for cid in chunk_ids if cid in by_id]
        present = [cid for cid in chunk_ids if cid in by_id]
        if not docs:
            return {}
        ranked = self.provider.rerank(query, docs)
        return {present[i]: score for i, score in ranked}

    def _to_candidates(
        self,
        chunk_ids: list[str],
        dense_scores: dict[str, float],
        rerank_scores: dict[str, float],
        fused_order: list[str],
    ) -> list[RetrievedCandidate]:
        by_id = {c.id: c for c in self.chunks}
        rrf_rank = {cid: i for i, cid in enumerate(fused_order, start=1)}
        out: list[RetrievedCandidate] = []
        for position, chunk_id in enumerate(chunk_ids, start=1):
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            out.append(RetrievedCandidate(
                chunk_id=chunk.source_id,
                text=chunk.text,
                source_ref=chunk.source_ref,
                rank=position,
                dense_score=dense_scores.get(chunk_id),
                rrf_score=1.0 / (RRF_K + rrf_rank[chunk_id]) if chunk_id in rrf_rank else None,
                rerank_score=rerank_scores.get(chunk_id),
            ))
        return out

    def _decide(self, candidates: list[RetrievedCandidate], dense_scores: dict[str, float]
                ) -> tuple[ReuseDecision, float]:
        """Calibrated decision plus a rank-1 / rank-2 margin confidence."""
        if not candidates:
            return ReuseDecision.STAKEHOLDER, 0.0

        best = max((c.dense_score for c in candidates if c.dense_score is not None),
                   default=None)
        if best is None:
            return ReuseDecision.STAKEHOLDER, 0.0

        decision = self.thresholds.decide(best)

        ordered = sorted(dense_scores.values(), reverse=True)[:2]
        if len(ordered) < 2 or ordered[0] <= 0:
            confidence = 0.0
        else:
            # Normalized margin: how far clear the winner is of the runner-up.
            confidence = max(0.0, min(1.0, (ordered[0] - ordered[1]) / abs(ordered[0])))
        return decision, round(confidence, 4)
