"""A10 Consistency Checker — Phase 9. DETERMINISTIC: zero LLM calls.

Extracts every number, date, duration, currency figure and named entity across all
sections into a fact table, then checks that cost components sum to the stated total,
phase durations sum to the program duration, FTE peaks match the resource table, no
entity carries two different values, and percentages reconcile.
Out: ConsistencyReport with contradictions localized to section IDs.
"""
