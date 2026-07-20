"""Retrieval threshold calibration — Phase 2.

Contract: samples question pairs from the ingested corpus, computes the similarity
distribution, and writes percentile-derived REUSE / ADAPT / SYNTHESIZE / STAKEHOLDER
boundaries to config/thresholds.json plus a human-readable calibration_report.md.
Thresholds are never hardcoded anywhere else.
"""
