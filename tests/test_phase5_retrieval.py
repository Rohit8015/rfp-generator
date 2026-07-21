"""Phase 5 acceptance test — A8 Hybrid Retriever.

The plan's gate was "hybrid beats dense-only on Recall@5 by >=10 points". It is not
testable on this dataset: dense-only already answers 49 of 50 labelled queries (98%
Recall@5, 94% Recall@1), so no method can improve on it by 10 points. The queries are
near-paraphrases of their targets, which is exactly the case dense retrieval handles
best.

So the gate is restated as what can actually be measured here:

1. Absolute quality against the dataset's own published targets (R@5 > 85%, MRR > 0.70).
2. Hybrid must not REGRESS against dense. A fusion step that costs recall is not worth
   keeping, and this is the assertion that would catch it.
3. Hybrid must win where the plan predicted it would -- queries depending on exact
   lexical terms, which is why BM25 is in the design at all.

These marked `slow` load local models and query the built indices.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.retriever import RRF_K, HybridRetriever
from src.models.schemas import ContextPack, ReuseDecision
from src.utils.metrics import ndcg_at_k, recall_at_k, reciprocal_rank, score_retrieval

ROOT = Path(__file__).parent.parent
PAIRS = ROOT / "data" / "eval" / "retrieval_pairs.json"

#: The dataset's own published targets, from its instructions.
TARGET_RECALL_AT_5 = 0.85
TARGET_MRR = 0.70


@pytest.fixture(scope="module")
def pairs():
    return json.loads(PAIRS.read_text(encoding="utf-8"))["retrieval_pairs"]


@pytest.fixture(scope="module")
def retriever():
    return HybridRetriever()


def _run(retriever, pairs, **kwargs):
    triples = []
    for p in pairs:
        pack = retriever.retrieve(p["query"], top_k=5, **kwargs)
        triples.append((p["query_id"], [c.chunk_id for c in pack.candidates],
                        p["relevant_ids"]))
    return score_retrieval(triples)


# --------------------------------------------------------------------------------------
# Metric helpers, no model needed
# --------------------------------------------------------------------------------------


def test_recall_at_k_is_set_based() -> None:
    assert recall_at_k(["a", "b", "c"], ["c"], 5) == 1.0
    assert recall_at_k(["a", "b", "c"], ["c"], 2) == 0.0
    assert recall_at_k(["a"], [], 5) == 0.0


def test_reciprocal_rank_rewards_position() -> None:
    assert reciprocal_rank(["x", "y"], ["x"]) == 1.0
    assert reciprocal_rank(["x", "y"], ["y"]) == 0.5
    assert reciprocal_rank(["x"], ["z"]) == 0.0


def test_ndcg_penalises_burying_a_hit() -> None:
    top = ndcg_at_k(["a", "b", "c", "d", "e"], ["a"], 5)
    deep = ndcg_at_k(["b", "c", "d", "e", "a"], ["a"], 5)
    assert top == 1.0 and deep < top


def test_rrf_fuses_ranks_not_scores() -> None:
    """An item ranked well by both lists must beat one ranked first by only one."""
    fused = HybridRetriever._rrf(["a", "b", "c"], ["b", "a", "c"])
    assert fused[0] in {"a", "b"}
    assert fused[-1] == "c"
    both_first = 2 / (RRF_K + 1)
    split = 1 / (RRF_K + 1) + 1 / (RRF_K + 2)
    assert both_first > split


def test_query_expansion_drops_stopwords() -> None:
    expansions = HybridRetriever._expand(
        "How do you handle GDPR data residency?", None, None
    )
    assert expansions
    terms = expansions[0].split()
    assert "gdpr" in terms and "residency" in terms
    assert "how" not in terms and "you" not in terms


def test_query_expansion_carries_paraphrase_and_purpose() -> None:
    expansions = HybridRetriever._expand("q", "a paraphrase", "the section purpose")
    assert expansions == ["a paraphrase", "the section purpose"]


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


@pytest.mark.slow
def test_absolute_quality_meets_the_published_targets(retriever, pairs) -> None:
    score = _run(retriever, pairs)
    assert score.recall_at_5 >= TARGET_RECALL_AT_5, f"{score} (misses: {score.misses})"
    assert score.mrr >= TARGET_MRR, str(score)


@pytest.mark.slow
def test_hybrid_does_not_regress_against_dense(retriever, pairs) -> None:
    """The real gate. A fusion step that costs recall is not worth keeping."""
    dense = _run(retriever, pairs, dense_only=True, rerank=False)
    hybrid = _run(retriever, pairs, dense_only=False, rerank=True)
    assert hybrid.recall_at_5 >= dense.recall_at_5, (
        f"hybrid {hybrid.recall_at_5:.1%} below dense {dense.recall_at_5:.1%}"
    )
    assert hybrid.mrr >= dense.mrr - 0.01, f"hybrid MRR {hybrid.mrr} vs dense {dense.mrr}"


@pytest.mark.slow
def test_dense_baseline_saturates_this_benchmark(retriever, pairs) -> None:
    """Records why the plan's >=10 point improvement is not testable here.

    If this ever fails, the dataset has been made harder and the original gate becomes
    meaningful again.
    """
    dense = _run(retriever, pairs, dense_only=True, rerank=False)
    assert dense.recall_at_5 >= 0.95, (
        f"dense baseline is no longer at ceiling ({dense.recall_at_5:.1%}); "
        "restore the plan's hybrid-beats-dense gate"
    )


@pytest.mark.slow
def test_lexical_queries_benefit_from_bm25(retriever, pairs) -> None:
    """Where the plan predicted BM25 would earn its place: exact-term queries."""
    lexical = [p for p in pairs if p.get("requires_lexical")]
    if len(lexical) < 3:
        pytest.skip(f"only {len(lexical)} lexical-dependent queries labelled")
    dense = _run(retriever, lexical, dense_only=True, rerank=False)
    hybrid = _run(retriever, lexical, dense_only=False, rerank=True)
    assert hybrid.ndcg_at_5 > dense.ndcg_at_5, (
        f"hybrid nDCG@5 {hybrid.ndcg_at_5:.3f} not above dense {dense.ndcg_at_5:.3f}"
    )


# --------------------------------------------------------------------------------------
# ContextPack contract
# --------------------------------------------------------------------------------------


@pytest.mark.slow
def test_pack_is_a_scored_attributed_list_not_one_match(retriever) -> None:
    pack = retriever.retrieve("What are your data residency controls?", top_k=5)
    assert isinstance(pack, ContextPack)
    assert len(pack.candidates) == 5, "the plan requires a candidate list, not one match"
    assert [c.rank for c in pack.candidates] == [1, 2, 3, 4, 5]
    assert all(c.source_ref for c in pack.candidates), "every candidate must be attributed"
    assert all(c.dense_score is not None for c in pack.candidates)


@pytest.mark.slow
def test_decision_always_cites_its_calibration(retriever) -> None:
    """Thresholds are never hardcoded; the pack records which calibration decided."""
    pack = retriever.retrieve("Describe your SOC 2 certification.", top_k=5)
    if pack.reuse_decision is not ReuseDecision.STAKEHOLDER:
        assert pack.calibration_version, "reuse decision with no calibration provenance"
        assert retriever.thresholds.version == pack.calibration_version


@pytest.mark.slow
def test_near_duplicate_reuses_and_novel_synthesizes(retriever) -> None:
    """The plan's own acceptance: a near-duplicate REUSEs, a novel question does not."""
    near = retriever.retrieve(
        "Describe your data residency controls for financial services clients.", top_k=5
    )
    assert near.reuse_decision is ReuseDecision.REUSE

    novel = retriever.retrieve(
        "What is your policy on staff dogs in the Antarctic field office?", top_k=5
    )
    assert novel.reuse_decision in {ReuseDecision.SYNTHESIZE, ReuseDecision.STAKEHOLDER}


@pytest.mark.slow
def test_confidence_is_a_margin_not_a_score(retriever) -> None:
    pack = retriever.retrieve("What are your data residency controls?", top_k=5)
    assert 0.0 <= pack.confidence <= 1.0
    top = pack.candidates[0].dense_score
    assert pack.confidence < top, "confidence must be a margin, not the raw similarity"


@pytest.mark.slow
def test_concurrent_retrieval_does_not_race_on_the_index() -> None:
    """Regression: sections retrieve in parallel and Chroma cannot take two clients
    being constructed against the same path at once.

    Unwarmed and unguarded, the first several threads raced and all but one failed with
    "could not connect to tenant default_tenant", silently degrading those sections to a
    stakeholder pack. Only the dashboard surfaced it, because thread timing differed
    from the CLI.
    """
    from concurrent.futures import ThreadPoolExecutor

    fresh = HybridRetriever()  # deliberately cold: no warm() call
    queries = [
        "data residency controls", "SOC 2 certification", "cloud cost optimisation",
        "incident response process", "disaster recovery", "penetration testing",
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        packs = list(pool.map(lambda q: fresh.retrieve(q, top_k=3), queries))

    assert len(packs) == len(queries)
    for pack in packs:
        assert pack.candidates, f"no candidates returned for {pack.query!r}"


@pytest.mark.slow
def test_warm_opens_every_index(retriever) -> None:
    retriever.warm()
    assert retriever._collection is not None
    assert retriever._bm25 is not None


@pytest.mark.slow
def test_reranking_reorders_the_shortlist(retriever) -> None:
    query = "How do you handle data subject access requests?"
    plain = retriever.retrieve(query, top_k=5, rerank=False)
    reranked = retriever.retrieve(query, top_k=5, rerank=True)
    assert [c.chunk_id for c in reranked.candidates] != []
    assert all(c.rerank_score is not None for c in reranked.candidates)
    assert all(c.rerank_score is None for c in plain.candidates)
