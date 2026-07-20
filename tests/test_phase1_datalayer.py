"""Phase 1 acceptance test.

Gate: round-trip one row per table; schemas validate on sample payloads.
Also asserts the plan's hard rules are enforced by the contracts themselves, so a later
agent cannot construct an illegal object and have it reach the database.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import db
from src.models.schemas import (
    AssuranceFinding,
    BidAssessment,
    BidVerdict,
    ComplianceMatrix,
    ComplianceRow,
    ConsistencyReport,
    Contradiction,
    ContextPack,
    DeliverableForm,
    DocumentNode,
    DocumentTree,
    Fit,
    FindingType,
    GeneratedSection,
    OutlineMode,
    OutlineSection,
    Priority,
    ProofMatch,
    ProofPoint,
    ProvenanceKind,
    ProvenanceRecord,
    RAG,
    ReqType,
    Requirement,
    ResponseOutline,
    ReuseDecision,
    RetrievedCandidate,
    RunRecord,
    SectionStatus,
    Severity,
    WinTheme,
)

RUN_ID = "run-0001"


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


# --------------------------------------------------------------------------------------
# Round-trip: one row per table
# --------------------------------------------------------------------------------------


@pytest.fixture()
def run(conn) -> RunRecord:
    r = RunRecord(id=RUN_ID, rfp_path="data/incoming/seed.md", mode=OutlineMode.NARRATIVE)
    db.save_run(conn, r)
    return r


def test_all_tables_created(conn) -> None:
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert set(db.TABLES).issubset(names), f"missing tables: {set(db.TABLES) - names}"


def test_roundtrip_runs(conn, run) -> None:
    run.status = "COMPLETE"
    run.sections_total = 10
    run.sections_automated = 7
    run.automation_rate = 70.0
    run.timings = {"A2_requirements": 12.5}
    run.token_counts = {"A2_requirements": 3100}
    db.save_run(conn, run)

    got = db.load_run(conn, RUN_ID)
    assert got is not None
    assert got.automation_rate == 70.0
    assert got.mode is OutlineMode.NARRATIVE
    assert got.timings == {"A2_requirements": 12.5}
    assert got.token_counts == {"A2_requirements": 3100}


def test_roundtrip_requirements(conn, run) -> None:
    req = Requirement(
        id="R-001",
        source_section="3.2",
        text="The supplier shall be GDPR compliant.",
        req_type=ReqType.SHALL_REQUIREMENT,
        priority=Priority.MANDATORY,
        deliverable_form=DeliverableForm.PROSE,
        cue_evidence="shall",
        extracted_by="both",
    )
    db.save_requirements(conn, RUN_ID, [req])
    assert db.load_requirements(conn, RUN_ID) == [req]


def test_roundtrip_sections(conn, run) -> None:
    db.save_section(
        conn,
        RUN_ID,
        id="S-01",
        order_index=0,
        title="Delivery Approach",
        purpose="Show a credible plan",
        deliverable_form=DeliverableForm.PROSE,
        status=SectionStatus.DRAFTED,
        requirement_ids=["R-001"],
        themes=["T-01"],
        target_words=600,
        content_md="We will deliver in three phases.",
        retry_count=1,
    )
    rows = db.load_sections(conn, RUN_ID)
    assert len(rows) == 1
    assert rows[0]["requirement_ids"] == ["R-001"]
    assert rows[0]["deliverable_form"] is DeliverableForm.PROSE
    assert rows[0]["status"] is SectionStatus.DRAFTED


def test_roundtrip_win_themes(conn, run) -> None:
    theme = WinTheme(
        id="T-01",
        statement="Your team cuts cost-to-serve without headcount change.",
        buyer_pain_addressed="Rising operational cost",
        proof_ids=["P-01"],
        requirement_ids_covered=["R-001", "R-002"],
    )
    db.save_win_themes(conn, RUN_ID, [theme])
    assert db.load_win_themes(conn, RUN_ID) == [theme]


def test_roundtrip_proof_points(conn) -> None:
    proof = ProofPoint(
        id="P-01",
        title="Retail bank migration",
        text="Cut cost-to-serve 22% in 9 months.",
        source_ref="case_studies/retail_bank.md",
        tags=["cost", "banking"],
    )
    db.save_proof_points(conn, [proof])
    assert db.load_proof_points(conn) == [proof]


def test_roundtrip_provenance(conn, run) -> None:
    rec = ProvenanceRecord(
        section_id="S-01",
        sentence_index=0,
        sentence="We delivered a comparable migration for a retail bank.",
        kind=ProvenanceKind.ADAPTED,
        source_ids=["P-01"],
        confidence=0.82,
    )
    db.save_provenance(conn, RUN_ID, [rec])
    assert db.load_provenance(conn, RUN_ID, "S-01") == [rec]


def test_roundtrip_assurance_findings(conn, run) -> None:
    finding = AssuranceFinding(
        finding_type=FindingType.CONTRADICTION,
        severity=Severity.BLOCKER,
        detail="Phase costs sum to 1.2M but total is stated as 1.1M.",
        section_id="S-04",
        evidence="1.2M vs 1.1M",
    )
    db.save_findings(conn, RUN_ID, [finding])
    assert db.load_findings(conn, RUN_ID) == [finding]


# --------------------------------------------------------------------------------------
# Database-level integrity
# --------------------------------------------------------------------------------------


def test_enum_check_constraint_rejects_bad_value(conn, run) -> None:
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO requirements (id, run_id, source_section, text, req_type,
                                         priority, deliverable_form)
               VALUES ('R-X', ?, '1', 't', 'NOT_A_TYPE', 'MANDATORY', 'PROSE')""",
            (RUN_ID,),
        )


def test_foreign_key_rejects_orphan_requirement(conn) -> None:
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO requirements (id, run_id, source_section, text, req_type,
                                         priority, deliverable_form)
               VALUES ('R-X', 'no-such-run', '1', 't', 'CONSTRAINT', 'MANDATORY', 'PROSE')"""
        )


def test_cascade_delete_clears_child_rows(conn, run) -> None:
    db.save_requirements(
        conn,
        RUN_ID,
        [
            Requirement(
                id="R-001",
                source_section="1",
                text="t",
                req_type=ReqType.CONSTRAINT,
                priority=Priority.MANDATORY,
                deliverable_form=DeliverableForm.PROSE,
            )
        ],
    )
    conn.execute("DELETE FROM runs WHERE id = ?", (RUN_ID,))
    conn.commit()
    assert db.load_requirements(conn, RUN_ID) == []


# --------------------------------------------------------------------------------------
# Contract rules from the plan, enforced in schemas
# --------------------------------------------------------------------------------------


def test_document_tree_walks_depth_first() -> None:
    tree = DocumentTree(
        source_path="x.md",
        roots=[
            DocumentNode(
                id="n1",
                numbering="1",
                title="Scope",
                level=0,
                children=[DocumentNode(id="n2", numbering="1.1", level=1)],
            )
        ],
    )
    assert [n.id for n in tree.nodes()] == ["n1", "n2"]


def test_winrate_below_20_forces_no_bid() -> None:
    with pytest.raises(ValidationError, match="must be NO_BID"):
        BidAssessment(
            mandatory_fit_pct=40.0,
            effort_estimate_hours=100.0,
            winrate_estimate=15.0,
            verdict=BidVerdict.BID,
        )
    assert BidAssessment(
        mandatory_fit_pct=40.0,
        effort_estimate_hours=100.0,
        winrate_estimate=15.0,
        verdict=BidVerdict.NO_BID,
    ).verdict is BidVerdict.NO_BID


def test_theme_threading_fewer_than_two_requirements_is_rejected() -> None:
    with pytest.raises(ValidationError, match=">=2 requirements"):
        WinTheme(
            id="T-02",
            statement="We are a leader in X.",
            buyer_pain_addressed="none",
            proof_ids=["P-01"],
            requirement_ids_covered=["R-001"],
        )


def test_decorative_theme_is_representable_when_dropped() -> None:
    t = WinTheme(
        id="T-02",
        statement="We are a leader in X.",
        buyer_pain_addressed="none",
        requirement_ids_covered=["R-001"],
        dropped=True,
        drop_reason="threads only 1 requirement; decorative",
    )
    assert t.dropped and t.drop_reason


def test_dropped_theme_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="drop_reason"):
        WinTheme(id="T-03", statement="s", buyer_pain_addressed="p", dropped=True)


def test_gap_cannot_cite_proof() -> None:
    with pytest.raises(ValidationError, match="GAP cannot cite"):
        ProofMatch(requirement_id="R-001", fit=Fit.GAP, proof_ids=["P-01"])
    assert ProofMatch(requirement_id="R-001", fit=Fit.GAP).proof_ids == []


def test_outline_rejects_requirement_in_two_sections() -> None:
    common = dict(purpose="p", deliverable_form=DeliverableForm.PROSE)
    with pytest.raises(ValidationError, match="exactly one primary section"):
        ResponseOutline(
            mode=OutlineMode.COMPLIANCE,
            sections=[
                OutlineSection(id="S-01", order_index=0, title="A",
                               requirement_ids=["R-001"], **common),
                OutlineSection(id="S-02", order_index=1, title="B",
                               requirement_ids=["R-001"], **common),
            ],
        )


def test_outline_reports_orphans() -> None:
    outline = ResponseOutline(
        mode=OutlineMode.NARRATIVE,
        sections=[
            OutlineSection(id="S-01", order_index=0, title="A", purpose="p",
                           deliverable_form=DeliverableForm.PROSE,
                           requirement_ids=["R-001"])
        ],
    )
    assert outline.orphans(["R-001", "R-002"]) == ["R-002"]


def test_reused_sentence_needs_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one source"):
        ProvenanceRecord(section_id="S-01", sentence_index=0, sentence="s",
                         kind=ProvenanceKind.REUSED, source_ids=["a", "b"])


def test_synthesized_sentence_needs_at_least_one_source() -> None:
    with pytest.raises(ValidationError, match="SYNTHESIZED requires"):
        ProvenanceRecord(section_id="S-01", sentence_index=0, sentence="s",
                         kind=ProvenanceKind.SYNTHESIZED)


def test_computed_sentence_needs_no_source() -> None:
    rec = ProvenanceRecord(section_id="S-05", sentence_index=0,
                           sentence="Total programme cost is 1.1M.",
                           kind=ProvenanceKind.COMPUTED)
    assert rec.source_ids == []


def test_context_pack_requires_calibration_provenance() -> None:
    with pytest.raises(ValidationError, match="calibration_version is required"):
        ContextPack(query="q", reuse_decision=ReuseDecision.REUSE)
    pack = ContextPack(
        query="q",
        reuse_decision=ReuseDecision.REUSE,
        calibration_version="2026-07-20",
        candidates=[RetrievedCandidate(chunk_id="c1", text="t", source_ref="kb/a.md",
                                       rank=1, rerank_score=0.91)],
        confidence=0.4,
    )
    assert pack.candidates[0].rank == 1


def test_stakeholder_decision_needs_no_calibration() -> None:
    """A guardrail STAKEHOLDER route never consults retrieval, so it is exempt."""
    assert ContextPack(query="q", reuse_decision=ReuseDecision.STAKEHOLDER)


def test_section_with_stakeholder_sentence_is_not_automated() -> None:
    base = dict(section_id="S-01", deliverable_form=DeliverableForm.PROSE, title="A")
    auto = GeneratedSection(
        **base,
        sentences=[ProvenanceRecord(section_id="S-01", sentence_index=0, sentence="a",
                                    kind=ProvenanceKind.TEMPLATE)],
    )
    manual = GeneratedSection(
        **base,
        sentences=[ProvenanceRecord(section_id="S-01", sentence_index=0, sentence="a",
                                    kind=ProvenanceKind.STAKEHOLDER)],
    )
    assert auto.automated() is True
    assert manual.automated() is False
    assert GeneratedSection(**base).automated() is False


def test_retry_count_capped_at_two() -> None:
    with pytest.raises(ValidationError):
        GeneratedSection(section_id="S-01", title="A",
                         deliverable_form=DeliverableForm.PROSE, retry_count=3)


def test_compliance_coverage_and_uncovered() -> None:
    matrix = ComplianceMatrix(
        rows=[
            ComplianceRow(requirement_id="R-001", requirement_text="a",
                          priority=Priority.MANDATORY, section_id="S-01",
                          anchor="p1", rag=RAG.GREEN),
            ComplianceRow(requirement_id="R-002", requirement_text="b",
                          priority=Priority.WEIGHTED, rag=RAG.RED),
        ]
    )
    assert matrix.coverage_pct == 50.0
    assert [r.requirement_id for r in matrix.uncovered()] == ["R-002"]


def test_consistency_report_passes_only_when_empty() -> None:
    assert ConsistencyReport(facts_extracted=42).passed is True
    assert ConsistencyReport(
        facts_extracted=42,
        contradictions=[Contradiction(kind="SUM", detail="d", section_ids=["S-04"])],
    ).passed is False


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProofPoint(id="P-01", title="t", text="x", typo_field=1)


def test_run_cannot_automate_more_sections_than_it_has() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        RunRecord(id="r", rfp_path="p", sections_total=2, sections_automated=3)
