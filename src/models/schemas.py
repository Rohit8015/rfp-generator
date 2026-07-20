"""Pydantic contracts and enums — Phase 1.

Contract: every object passed between agents is defined here. No loose dicts cross an
agent boundary. Where the build plan states a hard rule about an object (a win theme
must thread >=2 requirements; a REUSED sentence has exactly one source), that rule is
enforced here as a validator rather than left to the agent that builds the object.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    """Base for every inter-agent object. Rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------
# Enums (plan section 6)
# --------------------------------------------------------------------------------------


class ReqType(str, Enum):
    EXPLICIT_QUESTION = "EXPLICIT_QUESTION"
    SHALL_REQUIREMENT = "SHALL_REQUIREMENT"
    IMPLIED_DELIVERABLE = "IMPLIED_DELIVERABLE"
    EVAL_CRITERION = "EVAL_CRITERION"
    CONSTRAINT = "CONSTRAINT"
    SUBMISSION_RULE = "SUBMISSION_RULE"


class Priority(str, Enum):
    MANDATORY = "MANDATORY"
    WEIGHTED = "WEIGHTED"
    NICE_TO_HAVE = "NICE_TO_HAVE"


class DeliverableForm(str, Enum):
    PROSE = "PROSE"
    TABLE = "TABLE"
    CHART = "CHART"
    GANTT = "GANTT"
    MATRIX = "MATRIX"
    COSTING = "COSTING"
    APPENDIX = "APPENDIX"


class Fit(str, Enum):
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    GAP = "GAP"


class ReuseDecision(str, Enum):
    REUSE = "REUSE"
    ADAPT = "ADAPT"
    SYNTHESIZE = "SYNTHESIZE"
    STAKEHOLDER = "STAKEHOLDER"


class ProvenanceKind(str, Enum):
    REUSED = "REUSED"
    ADAPTED = "ADAPTED"
    SYNTHESIZED = "SYNTHESIZED"
    TEMPLATE = "TEMPLATE"
    COMPUTED = "COMPUTED"
    STAKEHOLDER = "STAKEHOLDER"


class FindingType(str, Enum):
    CONTRADICTION = "CONTRADICTION"
    UNCOVERED_REQ = "UNCOVERED_REQ"
    UNGROUNDED = "UNGROUNDED"
    RISK_LANGUAGE = "RISK_LANGUAGE"
    VOICE_DRIFT = "VOICE_DRIFT"


class BidVerdict(str, Enum):
    BID = "BID"
    PARTNER_BID = "PARTNER_BID"
    NO_BID = "NO_BID"


class OutlineMode(str, Enum):
    """Compliance mode mirrors the buyer's structure; narrative mode is a proposal."""

    COMPLIANCE = "COMPLIANCE"
    NARRATIVE = "NARRATIVE"


class SectionStatus(str, Enum):
    PENDING = "PENDING"
    DRAFTED = "DRAFTED"
    FAILED_ASSURANCE = "FAILED_ASSURANCE"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    BLOCKER = "BLOCKER"


class RAG(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


LLMTier = Literal["cheap", "strong"]

#: Kinds a deterministic component may emit — no model was involved in producing them.
DETERMINISTIC_KINDS = frozenset(
    {ProvenanceKind.TEMPLATE, ProvenanceKind.COMPUTED, ProvenanceKind.STAKEHOLDER}
)

Pct = Annotated[float, Field(ge=0.0, le=100.0)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


# --------------------------------------------------------------------------------------
# Plane 1 — Comprehension
# --------------------------------------------------------------------------------------


class DocumentNode(Contract):
    """One node of the parsed RFP. Children nest arbitrarily deep."""

    id: str
    numbering: str | None = None
    title: str | None = None
    text: str = ""
    level: int = Field(ge=0)
    page: int | None = None
    labelled_by_llm: bool = False
    children: list[DocumentNode] = Field(default_factory=list)

    def walk(self) -> list[DocumentNode]:
        """Depth-first flatten, self first."""
        out = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


class DocumentTree(Contract):
    """A1 Document Structurer output."""

    source_path: str
    title: str | None = None
    roots: list[DocumentNode] = Field(default_factory=list)
    page_count: int | None = None

    def nodes(self) -> list[DocumentNode]:
        return [n for r in self.roots for n in r.walk()]


class Requirement(Contract):
    """A2 Requirement Extractor output. One extracted obligation or question."""

    id: str
    source_section: str
    text: str
    req_type: ReqType
    priority: Priority
    deliverable_form: DeliverableForm
    cue_evidence: str = ""
    extracted_by: Literal["cue", "llm", "both"] = "cue"


class EvalCriterion(Contract):
    name: str
    weight: float | None = Field(default=None, ge=0.0)


class BuyerProfile(Contract):
    """A3 output. Passed into every downstream generation prompt."""

    audience_roles: list[str] = Field(default_factory=list)
    stated_pains: list[str] = Field(default_factory=list)
    decision_constraints: list[str] = Field(default_factory=list)
    evaluation_criteria: list[EvalCriterion] = Field(default_factory=list)
    red_lines: list[str] = Field(default_factory=list)
    tone_register: str = "professional"
    submission_rules: list[str] = Field(default_factory=list)


class BidAssessment(Contract):
    """A4 output. Winrate below 20% forces NO_BID — enforced here, not in the agent."""

    mandatory_fit_pct: Pct
    gaps: list[str] = Field(default_factory=list)
    effort_estimate_hours: float = Field(ge=0.0)
    winrate_estimate: Pct
    verdict: BidVerdict
    driving_factors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _low_winrate_forces_no_bid(self) -> BidAssessment:
        if self.winrate_estimate < 20.0 and self.verdict is not BidVerdict.NO_BID:
            raise ValueError(
                f"winrate {self.winrate_estimate}% is below 20%; verdict must be NO_BID"
            )
        return self


# --------------------------------------------------------------------------------------
# Plane 2 — Strategy
# --------------------------------------------------------------------------------------


class WinTheme(Contract):
    """A5 output. A theme threading <2 requirements is decorative and must be dropped."""

    id: str
    statement: str
    buyer_pain_addressed: str
    proof_ids: list[str] = Field(default_factory=list)
    requirement_ids_covered: list[str] = Field(default_factory=list)
    dropped: bool = False
    drop_reason: str | None = None

    @model_validator(mode="after")
    def _surviving_themes_must_thread(self) -> WinTheme:
        if self.dropped:
            if not self.drop_reason:
                raise ValueError("a dropped theme must carry a drop_reason")
            return self
        if len(self.requirement_ids_covered) < 2:
            raise ValueError(
                "a surviving theme must cover >=2 requirements; "
                "set dropped=True with a reason instead"
            )
        if not self.proof_ids:
            raise ValueError("a surviving theme must cite >=1 proof point")
        return self


class OutlineSection(Contract):
    """One planned section of the response."""

    id: str
    order_index: int = Field(ge=0)
    title: str
    purpose: str
    requirement_ids: list[str] = Field(default_factory=list)
    deliverable_form: DeliverableForm
    target_words: int = Field(default=400, ge=0)
    themes_to_carry: list[str] = Field(default_factory=list)
    source_hints: list[str] = Field(default_factory=list)


class ResponseOutline(Contract):
    """A6 output. The outline *is* the compliance matrix skeleton."""

    mode: OutlineMode
    sections: list[OutlineSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_primary_section_per_requirement(self) -> ResponseOutline:
        seen: dict[str, str] = {}
        for section in self.sections:
            for rid in section.requirement_ids:
                if rid in seen:
                    raise ValueError(
                        f"requirement {rid} assigned to both {seen[rid]} and "
                        f"{section.id}; each requirement has exactly one primary section"
                    )
                seen[rid] = section.id
        return self

    def covered_requirement_ids(self) -> set[str]:
        return {rid for s in self.sections for rid in s.requirement_ids}

    def orphans(self, all_requirement_ids: list[str]) -> list[str]:
        """Requirements the outline failed to place. Phase 6 gates on this being empty."""
        covered = self.covered_requirement_ids()
        return [r for r in all_requirement_ids if r not in covered]


class ProofPoint(Contract):
    """A library item: a case study, certification or reference."""

    id: str
    title: str
    text: str
    source_ref: str = ""
    tags: list[str] = Field(default_factory=list)


class ProofMatch(Contract):
    """A7 output. GAPs are surfaced, never invented around."""

    requirement_id: str
    fit: Fit
    proof_ids: list[str] = Field(default_factory=list)
    rationale: str = ""

    @model_validator(mode="after")
    def _gap_cites_nothing(self) -> ProofMatch:
        if self.fit is Fit.GAP and self.proof_ids:
            raise ValueError("a GAP cannot cite proof points")
        if self.fit is not Fit.GAP and not self.proof_ids:
            raise ValueError(f"fit {self.fit.value} requires >=1 proof id")
        return self


# --------------------------------------------------------------------------------------
# Plane 3 — Generation
# --------------------------------------------------------------------------------------


class RetrievedCandidate(Contract):
    """One scored, attributed retrieval hit. Never collapsed to a single 'best match'."""

    chunk_id: str
    text: str
    source_ref: str
    rank: int = Field(ge=1)
    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


class ContextPack(Contract):
    """A8 output. A list of candidates plus a calibrated reuse decision."""

    query: str
    expanded_queries: list[str] = Field(default_factory=list)
    candidates: list[RetrievedCandidate] = Field(default_factory=list)
    reuse_decision: ReuseDecision
    confidence: Unit = 0.0
    calibration_version: str | None = None

    @model_validator(mode="after")
    def _decision_must_be_calibrated(self) -> ContextPack:
        # STAKEHOLDER is reachable by guardrail (Compliance/Legal/GAP) without retrieval,
        # so it is the one decision that needs no calibration provenance.
        if self.reuse_decision is not ReuseDecision.STAKEHOLDER and not self.calibration_version:
            raise ValueError(
                "reuse_decision must derive from calibrated thresholds; "
                "calibration_version is required"
            )
        return self


class ProvenanceRecord(Contract):
    """One sentence of generated output and where it came from.

    No untracked text reaches the assembled document.
    """

    section_id: str
    sentence_index: int = Field(ge=0)
    sentence: str
    kind: ProvenanceKind
    source_ids: list[str] = Field(default_factory=list)
    confidence: Unit | None = None

    @model_validator(mode="after")
    def _sources_match_kind(self) -> ProvenanceRecord:
        n = len(self.source_ids)
        if self.kind in (ProvenanceKind.REUSED, ProvenanceKind.ADAPTED) and n != 1:
            raise ValueError(f"{self.kind.value} requires exactly one source id, got {n}")
        if self.kind is ProvenanceKind.SYNTHESIZED and n < 1:
            raise ValueError("SYNTHESIZED requires >=1 source id")
        return self


class GeneratedSection(Contract):
    """A9 output for one section, with provenance on every sentence."""

    section_id: str
    title: str
    deliverable_form: DeliverableForm
    content_md: str = ""
    sentences: list[ProvenanceRecord] = Field(default_factory=list)
    asset_paths: list[str] = Field(default_factory=list)
    status: SectionStatus = SectionStatus.PENDING
    retry_count: int = Field(default=0, ge=0, le=2)

    def automated(self) -> bool:
        """A section counts as automated only if no sentence needed a human."""
        return bool(self.sentences) and all(
            s.kind is not ProvenanceKind.STAKEHOLDER for s in self.sentences
        )


# --------------------------------------------------------------------------------------
# Plane 4 — Assurance
# --------------------------------------------------------------------------------------


class Contradiction(Contract):
    kind: str
    detail: str
    section_ids: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class ConsistencyReport(Contract):
    """A10 output. Deterministic — no model produced any part of this."""

    facts_extracted: int = Field(default=0, ge=0)
    contradictions: list[Contradiction] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.contradictions


class ComplianceRow(Contract):
    requirement_id: str
    requirement_text: str
    priority: Priority
    section_id: str | None = None
    anchor: str | None = None
    rag: RAG


class ComplianceMatrix(Contract):
    """A11 output. RAG-coded, with an explicit coverage percentage."""

    rows: list[ComplianceRow] = Field(default_factory=list)

    @property
    def coverage_pct(self) -> float:
        if not self.rows:
            return 0.0
        covered = sum(1 for r in self.rows if r.section_id)
        return round(100.0 * covered / len(self.rows), 2)

    def uncovered(self) -> list[ComplianceRow]:
        return [r for r in self.rows if not r.section_id]


class AssuranceFinding(Contract):
    """Any A10-A13 finding. Findings are flags for review, never silent deletions."""

    finding_type: FindingType
    severity: Severity
    detail: str
    section_id: str | None = None
    requirement_id: str | None = None
    evidence: str = ""
    resolved: bool = False


# --------------------------------------------------------------------------------------
# Run records
# --------------------------------------------------------------------------------------


class RunRecord(Contract):
    """One pipeline execution. Carries the governing metric and per-agent timings."""

    id: str
    rfp_path: str
    mode: OutlineMode | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
    status: str = "RUNNING"
    sections_total: int = Field(default=0, ge=0)
    sections_automated: int = Field(default=0, ge=0)
    automation_rate: Pct | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    token_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _automated_within_total(self) -> RunRecord:
        if self.sections_automated > self.sections_total:
            raise ValueError("sections_automated cannot exceed sections_total")
        return self


class AutomationReport(Contract):
    """W3 output. The project's headline number, reported per section type."""

    run_id: str
    overall_automation_rate: Pct
    rate_by_form: dict[str, float] = Field(default_factory=dict)
    provenance_breakdown: dict[str, int] = Field(default_factory=dict)
    gap_requirement_ids: list[str] = Field(default_factory=list)
    consistency_passed: bool = True
    compliance_coverage_pct: Pct = 0.0


DocumentNode.model_rebuild()
