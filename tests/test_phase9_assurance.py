"""Phase 9 acceptance test — the assurance plane, A10 to A13.

Gate, using data/eval/adversarial/: an injected arithmetic contradiction is caught and
localized; a deleted section drops compliance coverage and names the uncovered
requirement; an injected fabricated statistic is flagged UNGROUNDED; a "we guarantee
100%" sentence is flagged as risk language.

Each adversarial document carries exactly one defect, so the tests also assert that the
WRONG components stay quiet. A checker that fires on everything is useless, and that is
the failure mode the plan explicitly warns about for groundedness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.assurance.compliance import (
    ComplianceVerifier,
    coverage_findings,
    render_matrix,
)
from src.assurance.consistency import ConsistencyChecker
from src.assurance.grounding import GroundednessChecker, groundedness_rate
from src.assurance.polish import VoicePolisher, blocking_findings
from src.models.schemas import (
    RAG,
    DeliverableForm,
    FindingType,
    GeneratedSection,
    OutlineMode,
    OutlineSection,
    Priority,
    ProvenanceKind,
    ProvenanceRecord,
    ReqType,
    Requirement,
    ResponseOutline,
    SectionStatus,
    Severity,
)

ROOT = Path(__file__).parent.parent
ADVERSARIAL = ROOT / "data" / "eval" / "adversarial"


def _adversarial(name: str) -> GeneratedSection:
    path = ADVERSARIAL / f"{name}.md"
    content = path.read_text(encoding="utf-8")
    return GeneratedSection(
        section_id=name, title=name, deliverable_form=DeliverableForm.PROSE,
        content_md=content,
        sentences=[ProvenanceRecord(section_id=name, sentence_index=0,
                                    sentence=content[:200],
                                    kind=ProvenanceKind.SYNTHESIZED,
                                    source_ids=["HQ-001"])],
    )


def _requirement(rid: str, text: str, priority=Priority.MANDATORY) -> Requirement:
    return Requirement(id=rid, source_section="2.1", text=text,
                       req_type=ReqType.SHALL_REQUIREMENT, priority=priority,
                       deliverable_form=DeliverableForm.PROSE)


# --------------------------------------------------------------------------------------
# A10 Consistency
# --------------------------------------------------------------------------------------


def test_injected_arithmetic_error_is_caught_and_localized() -> None:
    report = ConsistencyChecker().check([_adversarial("adv_arithmetic")])
    assert not report.passed
    totals = [c for c in report.contradictions if c.kind == "TABLE_TOTAL"]
    assert totals, f"arithmetic error missed: {report.contradictions}"
    assert "adv_arithmetic" in totals[0].section_ids, "contradiction not localized"
    assert "41.95" in totals[0].detail and "38.25" in totals[0].detail


def test_injected_percentage_error_is_caught() -> None:
    report = ConsistencyChecker().check([_adversarial("adv_arithmetic")])
    pct = [c for c in report.contradictions if c.kind == "PERCENTAGE"]
    assert pct, "contingency percentage mismatch missed"
    assert "3.77" in pct[0].detail


def test_injected_duration_mismatch_is_caught() -> None:
    report = ConsistencyChecker().check([_adversarial("adv_duration")])
    durations = [c for c in report.contradictions if c.kind == "DURATION"]
    assert durations, f"duration mismatch missed: {report.contradictions}"
    assert "16.6" in durations[0].detail and "34" in durations[0].detail


def test_injected_entity_conflict_is_caught() -> None:
    report = ConsistencyChecker().check([_adversarial("adv_entity")])
    conflicts = [c for c in report.contradictions if c.kind == "ENTITY_VALUE"]
    assert conflicts, f"FTE conflict missed: {report.contradictions}"
    assert "24" in conflicts[0].detail and "31" in conflicts[0].detail


def test_each_contradiction_is_reported_once() -> None:
    """A finding restated three times trains a reviewer to skim the list."""
    report = ConsistencyChecker().check([_adversarial("adv_duration")])
    details = [(c.kind, c.detail) for c in report.contradictions]
    assert len(details) == len(set(details))


def test_consistency_stays_quiet_on_other_defects() -> None:
    """Fabrication and overclaiming are not A10's job."""
    for name in ["adv_fabrication", "adv_overclaim", "adv_missing_section"]:
        report = ConsistencyChecker().check([_adversarial(name)])
        assert report.passed, f"A10 fired on {name}: {report.contradictions}"


def test_a_reconciling_document_passes() -> None:
    good = GeneratedSection(
        section_id="S-01", title="Costs", deliverable_form=DeliverableForm.COSTING,
        content_md=(
            "## Costs\n\n| Component | Amount |\n|---|---|\n"
            "| Services | 10.00 |\n| Cloud | 5.00 |\n| **TOTAL** | **15.00** |\n"
        ),
    )
    assert ConsistencyChecker().check([good]).passed


def test_consistency_makes_no_model_call() -> None:
    source = (ROOT / "src" / "assurance" / "consistency.py").read_text(encoding="utf-8")
    for forbidden in ["get_provider", ".generate(", ".embed("]:
        assert forbidden not in source.lower(), f"consistency.py calls {forbidden}"


# --------------------------------------------------------------------------------------
# A11 Compliance
# --------------------------------------------------------------------------------------


@pytest.fixture()
def compliance_fixture():
    requirements = [
        _requirement("R-001", "The vendor shall implement a customer onboarding platform "
                              "supporting KYC and eSign verification."),
        _requirement("R-002", "The vendor shall provide a mobile loan origination system "
                              "with offline capability."),
        _requirement("R-003", "The vendor shall maintain a dedicated support team.",
                     Priority.WEIGHTED),
    ]
    outline = ResponseOutline(mode=OutlineMode.NARRATIVE, sections=[
        OutlineSection(id="S-01", order_index=0, title="Approach", purpose="p",
                       requirement_ids=["R-001", "R-002"],
                       deliverable_form=DeliverableForm.PROSE),
        OutlineSection(id="S-02", order_index=1, title="Support", purpose="p",
                       requirement_ids=["R-003"],
                       deliverable_form=DeliverableForm.PROSE),
    ])
    sections = [
        GeneratedSection(
            section_id="S-01", title="Approach", deliverable_form=DeliverableForm.PROSE,
            content_md=("## Approach\n\nWe implement a customer onboarding platform "
                        "supporting KYC and eSign verification.\n\n"
                        "The mobile loan origination system works offline.\n"),
            status=SectionStatus.DRAFTED,
        ),
        GeneratedSection(
            section_id="S-02", title="Support", deliverable_form=DeliverableForm.PROSE,
            content_md="## Support\n\nA dedicated support team is maintained.\n",
            status=SectionStatus.DRAFTED,
        ),
    ]
    return requirements, outline, sections


def test_full_coverage_when_everything_is_written(compliance_fixture) -> None:
    requirements, outline, sections = compliance_fixture
    matrix = ComplianceVerifier().verify(requirements, outline, sections)
    assert matrix.coverage_pct == 100.0
    assert not matrix.uncovered()
    assert all(r.anchor for r in matrix.rows), "every row needs a paragraph anchor"


def test_deleting_a_section_drops_coverage_and_names_the_requirement(
    compliance_fixture,
) -> None:
    """The plan's gate."""
    requirements, outline, sections = compliance_fixture
    reduced = [s for s in sections if s.section_id != "S-02"]

    matrix = ComplianceVerifier().verify(requirements, outline, reduced)
    assert matrix.coverage_pct < 100.0
    uncovered = [r.requirement_id for r in matrix.uncovered()]
    assert uncovered == ["R-003"]

    findings = coverage_findings(matrix)
    assert any(f.requirement_id == "R-003"
               and f.finding_type is FindingType.UNCOVERED_REQ for f in findings)


def test_escalated_section_does_not_count_as_covered(compliance_fixture) -> None:
    """Intent is not delivery. An escalated section must reduce coverage."""
    requirements, outline, sections = compliance_fixture
    sections[1].status = SectionStatus.ESCALATED
    matrix = ComplianceVerifier().verify(requirements, outline, sections)
    assert matrix.coverage_pct < 100.0
    row = next(r for r in matrix.rows if r.requirement_id == "R-003")
    assert row.rag is RAG.RED
    assert "escalated" in (row.anchor or "")


def test_missing_mandatory_requirement_is_a_blocker(compliance_fixture) -> None:
    requirements, outline, sections = compliance_fixture
    matrix = ComplianceVerifier().verify(requirements, outline,
                                         [s for s in sections if s.section_id == "S-02"])
    findings = coverage_findings(matrix)
    blockers = [f for f in findings if f.severity is Severity.BLOCKER]
    assert {f.requirement_id for f in blockers} == {"R-001", "R-002"}


def test_weakly_addressed_requirement_is_amber(compliance_fixture) -> None:
    requirements, outline, sections = compliance_fixture
    sections[1].content_md = "## Support\n\nWe will discuss this during mobilisation.\n"
    matrix = ComplianceVerifier().verify(requirements, outline, sections)
    row = next(r for r in matrix.rows if r.requirement_id == "R-003")
    assert row.rag is RAG.AMBER


def test_matrix_renders_with_coverage(compliance_fixture) -> None:
    requirements, outline, sections = compliance_fixture
    rendered = render_matrix(ComplianceVerifier().verify(requirements, outline, sections))
    assert "Coverage:" in rendered and "100.0%" in rendered
    assert all(r.id in rendered for r in requirements)


def test_compliance_makes_no_model_call() -> None:
    source = (ROOT / "src" / "assurance" / "compliance.py").read_text(encoding="utf-8")
    for forbidden in ["get_provider", ".generate(", ".embed("]:
        assert forbidden not in source.lower(), f"compliance.py calls {forbidden}"


# --------------------------------------------------------------------------------------
# A13 Voice and risk
# --------------------------------------------------------------------------------------


def test_injected_overclaim_is_flagged() -> None:
    """The plan's gate: 'we guarantee 100% uptime' must be caught."""
    findings = VoicePolisher().review([_adversarial("adv_overclaim")])
    risk = [f for f in findings if f.finding_type is FindingType.RISK_LANGUAGE]
    assert risk, "overclaiming language missed"
    blob = " ".join(f.detail.lower() for f in risk)
    assert "guarantee" in blob
    assert any("100" in f.detail for f in risk)
    assert any("unlimited" in f.detail.lower() for f in risk)
    assert blocking_findings(risk), "unbounded liability should be a blocker"


def test_measured_language_is_not_flagged() -> None:
    clean = GeneratedSection(
        section_id="S-01", title="Service levels",
        deliverable_form=DeliverableForm.PROSE,
        content_md=("## Service levels\n\nWe target 99.5% availability measured "
                    "monthly, with service credits where the target is missed. "
                    "Liability is capped at the annual charges paid.\n"),
    )
    findings = VoicePolisher().review([clean])
    assert not [f for f in findings if f.finding_type is FindingType.RISK_LANGUAGE]


def test_stakeholder_briefs_are_exempt_from_risk_review() -> None:
    """A brief describing what a human must write is not a claim to the client."""
    brief = GeneratedSection(
        section_id="S-05", title="Legal", deliverable_form=DeliverableForm.PROSE,
        content_md="## Legal\n\nThe client asks us to guarantee 100% uptime.\n",
        sentences=[ProvenanceRecord(section_id="S-05", sentence_index=0,
                                    sentence="The client asks us to guarantee 100% uptime.",
                                    kind=ProvenanceKind.STAKEHOLDER)],
    )
    assert not VoicePolisher().review([brief])


def test_voice_drift_needs_several_sections() -> None:
    one = GeneratedSection(section_id="S-01", title="T",
                           deliverable_form=DeliverableForm.PROSE,
                           content_md="## T\n\n" + "A simple sentence here. " * 20)
    assert not [f for f in VoicePolisher().review([one])
                if f.finding_type is FindingType.VOICE_DRIFT]


def test_voice_drift_flags_an_outlier() -> None:
    plain = "The team will deliver the work in phases. Each phase has a clear end. "
    dense = ("Notwithstanding the aforementioned contractual particularities, the "
             "implementation methodology necessitates comprehensive interdepartmental "
             "reconciliation of heterogeneous infrastructural dependencies. ")
    sections = [
        GeneratedSection(section_id=f"S-0{i}", title="T",
                         deliverable_form=DeliverableForm.PROSE,
                         content_md="## T\n\n" + plain * 6)
        for i in range(1, 6)
    ]
    sections.append(GeneratedSection(section_id="S-99", title="Odd",
                                     deliverable_form=DeliverableForm.PROSE,
                                     content_md="## Odd\n\n" + dense * 4))
    drift = [f for f in VoicePolisher().review(sections)
             if f.finding_type is FindingType.VOICE_DRIFT]
    assert drift and drift[0].section_id == "S-99"


def test_polish_makes_no_model_call() -> None:
    source = (ROOT / "src" / "assurance" / "polish.py").read_text(encoding="utf-8")
    for forbidden in ["get_provider", ".generate(", ".embed("]:
        assert forbidden not in source.lower(), f"polish.py calls {forbidden}"


# --------------------------------------------------------------------------------------
# A12 Groundedness
# --------------------------------------------------------------------------------------


def test_uncheckable_sentences_are_skipped() -> None:
    """Connective prose asserts nothing. Checking it wastes a call and risks a false flag."""
    checkable = GroundednessChecker.is_checkable
    assert not checkable("We will work with your team during discovery.")
    assert not checkable("This section describes our approach.")
    assert checkable("We delivered 85% automation for a top-5 NBFC.")
    assert checkable("All of our clients achieved positive ROI.")
    assert checkable("We are certified to ISO 27001.")


def test_an_uncited_claim_cannot_be_constructed() -> None:
    """The contract makes the unsourced-claim case unreachable, so grounding never
    has to catch it. This records that guarantee rather than assuming it.
    """
    from pydantic import ValidationError

    for kind in (ProvenanceKind.SYNTHESIZED, ProvenanceKind.REUSED,
                 ProvenanceKind.ADAPTED):
        with pytest.raises(ValidationError):
            ProvenanceRecord(
                section_id="S-01", sentence_index=0,
                sentence="We delivered 98.7% fraud reduction across all clients.",
                kind=kind, source_ids=[],
            )


def test_computed_and_template_text_is_not_grounding_checked() -> None:
    """Arithmetic is A10's job and is checked exactly, not judged."""
    section = GeneratedSection(
        section_id="S-09", title="Costs", deliverable_form=DeliverableForm.COSTING,
        content_md="## Costs\n\nThe total investment is 41.95 crore.\n",
        sentences=[ProvenanceRecord(section_id="S-09", sentence_index=0,
                                    sentence="The total investment is 41.95 crore.",
                                    kind=ProvenanceKind.COMPUTED)],
    )
    assert GroundednessChecker(provider=object()).check([section]) == []


def test_groundedness_rate_is_reported() -> None:
    section = GeneratedSection(
        section_id="S-01", title="T", deliverable_form=DeliverableForm.PROSE,
        content_md="## T\n\nWe hold ISO 27001. We delivered 85% automation.\n",
        sentences=[
            ProvenanceRecord(section_id="S-01", sentence_index=0,
                             sentence="We hold ISO 27001.",
                             kind=ProvenanceKind.REUSED, source_ids=["HQ-001"]),
            ProvenanceRecord(section_id="S-01", sentence_index=1,
                             sentence="We delivered 85% automation.",
                             kind=ProvenanceKind.REUSED, source_ids=["HQ-002"]),
        ],
    )
    assert groundedness_rate([section], []) == 100.0


@pytest.mark.live
def test_fabricated_statistics_are_flagged_ungrounded() -> None:
    """The plan's gate, against the adversarial fabrication document."""
    content = (ADVERSARIAL / "adv_fabrication.md").read_text(encoding="utf-8")
    claims = [
        "Our platform delivered a 98.7% reduction in fraud losses across all financial "
        "services clients.",
        "We achieved a 100% success rate in blockchain implementations with zero bugs.",
        "All transformation programmes achieved 200% ROI.",
    ]
    section = GeneratedSection(
        section_id="S-01", title="Client success", deliverable_form=DeliverableForm.PROSE,
        content_md=content,
        sentences=[
            ProvenanceRecord(section_id="S-01", sentence_index=i, sentence=c,
                             kind=ProvenanceKind.SYNTHESIZED, source_ids=["PP-001"])
            for i, c in enumerate(claims)
        ],
    )
    findings = GroundednessChecker().check([section])
    assert findings, "no fabricated statistic was flagged"
    assert all(f.finding_type is FindingType.UNGROUNDED for f in findings)


@pytest.mark.live
def test_grounding_meets_the_published_targets() -> None:
    """Measured on all 40 labelled pairs.

    Observed 2026-07-21: precision 0.909, recall 1.000, false positive rate 0.100.
    Bounds below are looser than those numbers because a model's verdicts vary between
    runs; they are set to catch a regression, not to certify a single lucky run.

    The plan calls false positives the key risk, and the two seen here look like label
    problems rather than checker problems: one flags a claim of "85% automation" with
    the reason that the source never mentions 85%, which is correct on the text.
    """
    import json

    from src.assurance.grounding import GroundednessChecker

    pairs = json.loads(
        (ROOT / "data" / "eval" / "grounding_labelled.json").read_text(encoding="utf-8")
    )["grounding_pairs"]

    sections, chunks = [], {}
    for index, pair in enumerate(pairs):
        source_id = f"CTX-{index:03d}"
        chunks[source_id] = pair["context"]
        sections.append(GeneratedSection(
            section_id=f"S-{index:03d}", title="t",
            deliverable_form=DeliverableForm.PROSE,
            content_md=f"## t\n\n{pair['claim']}\n",
            sentences=[ProvenanceRecord(
                section_id=f"S-{index:03d}", sentence_index=0, sentence=pair["claim"],
                kind=ProvenanceKind.SYNTHESIZED, source_ids=[source_id])],
        ))

    flagged = {f.section_id for f in GroundednessChecker(chunks=chunks).check(sections)}
    tp = fp = tn = fn = 0
    for index, pair in enumerate(pairs):
        was_flagged = f"S-{index:03d}" in flagged
        if not pair["is_supported"]:
            tp, fn = (tp + 1, fn) if was_flagged else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if was_flagged else (fp, tn + 1)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    false_positive_rate = fp / (fp + tn) if (fp + tn) else 0.0

    assert recall >= 0.80, f"recall {recall:.3f}: unsupported claims are getting through"
    assert precision >= 0.75, f"precision {precision:.3f}"
    assert false_positive_rate <= 0.20, (
        f"false positive rate {false_positive_rate:.3f}: a checker that flags supported "
        "claims trains reviewers to ignore it"
    )


@pytest.mark.live
def test_supported_claims_are_not_flagged() -> None:
    """False positive rate matters most: a checker that flags everything is useless."""
    from src.agents.proofs import ProofMatcher

    proof = ProofMatcher.load_library()[0]
    section = GeneratedSection(
        section_id="S-01", title="Evidence", deliverable_form=DeliverableForm.PROSE,
        content_md=f"## Evidence\n\n{proof.title}\n",
        sentences=[ProvenanceRecord(section_id="S-01", sentence_index=0,
                                    sentence=proof.title, kind=ProvenanceKind.REUSED,
                                    source_ids=[proof.id])],
    )
    findings = GroundednessChecker(chunks={proof.id: proof.text}).check([section])
    assert not findings, f"a supported claim was flagged: {[f.detail for f in findings]}"
