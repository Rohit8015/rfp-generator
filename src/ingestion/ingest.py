"""Corpus ingestion — Phase 2.

Contract: chunks and embeds data/knowledge_base, data/historical_rfps and
data/proof_library into Chroma, and builds the BM25 index over the same raw chunks.
Idempotent: re-running rebuilds cleanly rather than duplicating.
"""
