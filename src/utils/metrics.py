"""Evaluation metrics.

Recall, precision, Recall@k, MRR, nDCG@k, requirement coverage, groundedness rate and
the governing metric: automation rate, reported per section type.

Deterministic. No model call anywhere in this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# --------------------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------------------


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """1.0 if any relevant id appears in the top k. Set-based, not graded."""
    if not relevant:
        return 0.0
    return 1.0 if set(retrieved[:k]) & set(relevant) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    """1/rank of the first relevant hit, 0 if none."""
    wanted = set(relevant)
    for i, item in enumerate(retrieved, start=1):
        if item in wanted:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Binary-gain nDCG. Rewards putting relevant items higher, not merely present."""
    wanted = set(relevant)
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, item in enumerate(retrieved[:k], start=1)
        if item in wanted
    )
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(wanted), k) + 1))
    return dcg / ideal if ideal else 0.0


@dataclass
class RetrievalScore:
    """Aggregate retrieval quality over a labelled query set."""

    n: int = 0
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    misses: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"n={self.n}  R@1={self.recall_at_1:.1%}  R@5={self.recall_at_5:.1%}  "
            f"MRR={self.mrr:.3f}  nDCG@5={self.ndcg_at_5:.3f}"
        )


def score_retrieval(results: list[tuple[str, list[str], list[str]]]) -> RetrievalScore:
    """Score (query_id, retrieved_ids, relevant_ids) triples."""
    if not results:
        return RetrievalScore()
    r1 = r5 = mrr = ndcg = 0.0
    misses: list[str] = []
    for query_id, retrieved, relevant in results:
        hit5 = recall_at_k(retrieved, relevant, 5)
        r1 += recall_at_k(retrieved, relevant, 1)
        r5 += hit5
        mrr += reciprocal_rank(retrieved, relevant)
        ndcg += ndcg_at_k(retrieved, relevant, 5)
        if not hit5:
            misses.append(query_id)
    n = len(results)
    return RetrievalScore(
        n=n,
        recall_at_1=r1 / n,
        recall_at_5=r5 / n,
        mrr=mrr / n,
        ndcg_at_5=ndcg / n,
        misses=misses,
    )


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------


def precision_recall_f1(found: int, expected: int, retrieved_total: int
                        ) -> tuple[float, float, float]:
    recall = found / expected if expected else 0.0
    precision = found / retrieved_total if retrieved_total else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


# --------------------------------------------------------------------------------------
# The governing metric
# --------------------------------------------------------------------------------------


def automation_rate(sections) -> float:
    """Share of sections produced with zero human input, as a percentage.

    A section counts as automated only if no sentence in it carries STAKEHOLDER
    provenance. Partial credit would let a section that needed a human be reported as
    mostly automated, which is precisely the overclaim this metric exists to prevent.
    """
    sections = list(sections)
    if not sections:
        return 0.0
    return 100.0 * sum(1 for s in sections if s.automated()) / len(sections)


def sentence_automation_rate(sections) -> float:
    """Share of SENTENCES produced without human input.

    A weaker measure than `automation_rate`, and reported alongside it rather than
    instead of it. The section-level rate is the honest headline: a section needing one
    human sentence is a section a human must open. But when most sections carry a small
    carve-out, the section rate collapses to zero and stops distinguishing a document
    that is 95% drafted from one that is 5% drafted. This says which.
    """
    records = [r for s in sections for r in s.sentences]
    if not records:
        return 0.0
    from src.models.schemas import ProvenanceKind as _Kind

    automated = sum(1 for r in records if r.kind is not _Kind.STAKEHOLDER)
    return round(100.0 * automated / len(records), 1)


def automation_rate_by_form(sections) -> dict[str, float]:
    """Automation rate per deliverable form. The plan reports per section type."""
    buckets: dict[str, list] = {}
    for s in sections:
        buckets.setdefault(s.deliverable_form.value, []).append(s)
    return {form: round(automation_rate(items), 1) for form, items in buckets.items()}


def provenance_breakdown(sections) -> dict[str, int]:
    """Sentence counts per provenance kind, across every section."""
    counts: dict[str, int] = {}
    for section in sections:
        for record in section.sentences:
            counts[record.kind.value] = counts.get(record.kind.value, 0) + 1
    return counts
