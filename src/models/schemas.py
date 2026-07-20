"""Pydantic contracts and enums — Phase 1.

Contract: every object passed between agents is defined here. No loose dicts cross an
agent boundary. Holds DocumentTree, Requirement, BuyerProfile, BidAssessment, WinTheme,
ResponseOutline, ContextPack, GeneratedSection, ConsistencyReport, ComplianceMatrix,
AssuranceFinding, RunRecord, and the enums req_type / priority / deliverable_form /
fit / reuse_decision / provenance_kind / finding_type.
"""
