"""Pipeline orchestrator — Phase 10.

Chains all four planes and owns the section-level regeneration loop: any section
failing A10-A13 is re-drafted with the failure reason appended to its prompt, max 2
retries, then escalated to a human task. This loop is what makes the system agentic
rather than a chain.
"""
