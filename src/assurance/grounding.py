"""A12 Groundedness Checker — Phase 9. Uses the LLM.

Checks every factual claim in generated prose against its cited context chunk via a
batched sentence-level NLI-style check. Unsupported claims are flagged UNGROUNDED.
Findings are flags for human review, never silent deletions.
"""
