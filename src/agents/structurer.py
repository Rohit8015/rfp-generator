"""A1 Document Structurer — Phase 3.

In: RFP file path. Out: DocumentTree (nested sections, numbering, page refs, raw text).
Deterministic parse first (heading styles, numbering regex); the LLM is used only to
label untitled blocks.
"""
