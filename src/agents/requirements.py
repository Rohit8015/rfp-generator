"""A2 Requirement Extractor — Phase 3.

In: DocumentTree. Out: list[Requirement] with req_type, priority, deliverable_form and
cue_evidence. A deterministic Shipley cue-word pass is unioned with an LLM pass for
implied deliverables, then deduped. Gate: >=90% recall, 100% MANDATORY recall.
"""
