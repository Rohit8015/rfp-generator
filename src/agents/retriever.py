"""A8 Hybrid Retriever — Phase 5.

BM25 + dense -> Reciprocal Rank Fusion -> cross-encoder rerank of top-30.
Query expansion: original text + requirement paraphrase + section purpose.
Out: ContextPack, a list of scored attributed candidates. reuse_decision comes from
the calibrated thresholds; confidence is the normalized rank-1/rank-2 margin.
"""
