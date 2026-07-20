"""Phase 3 acceptance test — A1 Structurer and A2 Requirement Extractor.

Gate: >=90% overall recall and 100% MANDATORY recall against
data/eval/requirements_labelled.json.

The gated run uses the deterministic cue pass only (`use_llm=False`). That is the
stricter test and it makes the gate reproducible: a provider outage or a bad generation
cannot change whether Phase 3 passes. The LLM pass is exercised separately and marked
`live`, and is additive by construction, so it can only raise recall.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.requirements import RequirementExtractor
from src.agents.structurer import Structurer
from src.models.schemas import DeliverableForm, Priority, ReqType
from src.utils import docparse
from src.utils.eval_data import (
    DELIVERABLE_FORM_MAP,
    containment,
    load_labelled_requirements,
    similarity,
)

ROOT = Path(__file__).parent.parent
RFP_A = ROOT / "data" / "incoming" / "RFP-A_questionnaire_nbfc.md"

#: A labelled requirement counts as found when an extracted item is clearly the same
#: sentence. Both bars must be cleared: broad overlap AND near-total containment.
MATCH_SIMILARITY = 0.45
MATCH_CONTAINMENT = 0.75


@pytest.fixture(scope="module")
def tree():
    return Structurer(use_llm=False).parse(RFP_A)


@pytest.fixture(scope="module")
def extracted(tree):
    return RequirementExtractor(use_llm=False).extract(tree)


@pytest.fixture(scope="module")
def labelled():
    _, reqs = load_labelled_requirements()
    return reqs


def _match(target: str, candidates) -> object | None:
    best, best_score = None, 0.0
    for c in candidates:
        sim, con = similarity(target, c.text), containment(target, c.text)
        if sim >= MATCH_SIMILARITY and con >= MATCH_CONTAINMENT and sim > best_score:
            best, best_score = c, sim
    return best


# --------------------------------------------------------------------------------------
# A1 Structurer
# --------------------------------------------------------------------------------------


def test_structurer_reproduces_the_section_hierarchy(tree) -> None:
    numbered = {n.numbering: n.title for n in tree.nodes() if n.numbering}
    for numbering, fragment in [
        ("1", "Executive Summary"), ("2", "Scope of Work"),
        ("2.1", "Mandatory Requirements"), ("2.2", "Weighted Requirements"),
        ("2.3", "Nice-to-Have"), ("3", "Evaluation Criteria"),
        ("4", "Submission Requirements"), ("7", "Annexures"),
    ]:
        assert numbering in numbered, f"section {numbering} not found"
        assert fragment.lower() in (numbered[numbering] or "").lower(), (
            f"section {numbering} titled {numbered[numbering]!r}, expected ~{fragment!r}"
        )


def test_structurer_nests_subsections_under_their_parent(tree) -> None:
    scope = next(n for n in tree.nodes() if n.numbering == "2")
    child_numbers = {c.numbering for c in scope.children}
    assert {"2.1", "2.2", "2.3"} <= child_numbers


def test_structurer_keeps_section_bodies(tree) -> None:
    mandatory = next(n for n in tree.nodes() if n.numbering == "2.1")
    assert "R-001" in mandatory.text
    assert "R-012" in mandatory.text
    assert "R-013" not in mandatory.text, "2.1 must not absorb 2.2's body"


def test_structurer_needs_no_model(tree) -> None:
    """The deterministic path must work with no provider configured."""
    assert not any(n.labelled_by_llm for n in tree.nodes())
    assert len(tree.nodes()) > 5


def test_structurer_rejects_unknown_formats(tmp_path) -> None:
    bogus = tmp_path / "rfp.zip"
    bogus.write_bytes(b"not a document")
    with pytest.raises(docparse.UnsupportedDocument):
        Structurer(use_llm=False).parse(bogus)


def test_structurer_reports_a_missing_file_plainly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        Structurer(use_llm=False).parse(tmp_path / "absent.md")


# --------------------------------------------------------------------------------------
# A2 gate
# --------------------------------------------------------------------------------------


def test_overall_recall_meets_the_gate(extracted, labelled) -> None:
    found = [r for r in labelled if _match(r.text, extracted)]
    recall = len(found) / len(labelled)
    missed = [r.requirement_id for r in labelled if not _match(r.text, extracted)]
    assert recall >= 0.90, (
        f"recall {recall:.1%} below the 90% gate; missed {missed}"
    )


def test_mandatory_recall_is_total(extracted, labelled) -> None:
    """The plan gates MANDATORY at 100%. A missed must-win requirement loses the bid."""
    mandatory = [r for r in labelled if r.priority is Priority.MANDATORY]
    missed = [r.requirement_id for r in mandatory if not _match(r.text, extracted)]
    assert not missed, f"MANDATORY requirements missed: {missed}"


def test_priority_is_assigned_correctly(extracted, labelled) -> None:
    """Shipley cue banding: shall -> MANDATORY, should -> WEIGHTED, may -> NICE_TO_HAVE."""
    wrong = []
    for want in labelled:
        got = _match(want.text, extracted)
        if got and got.priority is not want.priority:
            wrong.append((want.requirement_id, want.priority.value, got.priority.value))
    accuracy = 1 - len(wrong) / len(labelled)
    assert accuracy >= 0.90, f"priority accuracy {accuracy:.1%}; mismatches: {wrong}"


def test_precision_is_reported_and_reasonable(extracted, labelled) -> None:
    """Recall bought with indiscriminate extraction is worthless."""
    matched = {id(_match(r.text, extracted)) for r in labelled}
    matched.discard(id(None))
    precision = len(matched) / len(extracted) if extracted else 0.0
    assert precision >= 0.50, (
        f"precision {precision:.1%}: too many extracted items match no labelled "
        f"requirement ({len(extracted)} extracted vs {len(labelled)} labelled)"
    )


def test_every_requirement_carries_cue_evidence(extracted) -> None:
    assert all(r.cue_evidence.strip() for r in extracted)


def test_ids_are_unique_and_stable(extracted) -> None:
    ids = [r.id for r in extracted]
    assert len(ids) == len(set(ids))
    assert all(r.id.startswith("R-") for r in extracted)


def test_source_sections_are_populated(extracted) -> None:
    assert all(r.source_section.strip() for r in extracted)


# --------------------------------------------------------------------------------------
# Typing behaviour
# --------------------------------------------------------------------------------------


def test_submission_rules_are_typed_as_such(extracted) -> None:
    submission = [r for r in extracted if r.source_section == "4"]
    assert submission, "section 4 produced no requirements"
    typed = [r for r in submission if r.req_type is ReqType.SUBMISSION_RULE]
    assert len(typed) / len(submission) >= 0.6, (
        f"only {len(typed)}/{len(submission)} of section 4 typed as SUBMISSION_RULE"
    )


def test_compliance_language_becomes_a_constraint(extracted) -> None:
    rbi = [r for r in extracted if "rbi guidelines" in r.text.lower()]
    assert rbi, "the RBI compliance requirement was not extracted"
    assert any(r.req_type is ReqType.CONSTRAINT for r in rbi)


def test_deliverable_form_uses_the_contract_enum(extracted) -> None:
    """Not the dataset's enum. This is what routes A9 to a writer in Phase 7."""
    assert all(isinstance(r.deliverable_form, DeliverableForm) for r in extracted)


def test_form_hints_match_on_word_boundaries() -> None:
    """Regression: the hint "nda" matched inside "ma-nda-tory".

    Substring matching routed every MANDATORY requirement to APPENDIX, which in Phase 7
    would send half the document to the boilerplate writer instead of the narrative one.
    """
    form = RequirementExtractor._deliverable_form
    assert form(
        "The vendor SHALL implement a unified customer onboarding platform.",
        "Mandatory Requirements (SHALL/REQUIRED)",
    ) is DeliverableForm.PROSE
    # And the hint still works when the word is genuinely present.
    assert form("Submit the signed NDA.", "Annexures") is DeliverableForm.APPENDIX


def test_mandatory_requirements_are_not_routed_to_boilerplate(extracted) -> None:
    strays = [
        (r.id, r.text[:50]) for r in extracted
        if r.priority is Priority.MANDATORY
        and r.deliverable_form is DeliverableForm.APPENDIX
        and "annexure" not in r.text.lower()
        and "escrow" not in r.text.lower()
        and "nda" not in r.text.lower().split()
    ]
    assert not strays, f"mandatory requirements routed to APPENDIX: {strays}"


def test_deliverable_forms_are_not_dominated_by_one_bucket(extracted) -> None:
    """A single form taking most of the document usually means a matching bug."""
    counts: dict[DeliverableForm, int] = {}
    for r in extracted:
        counts[r.deliverable_form] = counts.get(r.deliverable_form, 0) + 1
    non_prose = {f: c for f, c in counts.items() if f is not DeliverableForm.PROSE}
    for form, count in non_prose.items():
        assert count / len(extracted) < 0.35, (
            f"{form.value} claims {count}/{len(extracted)} requirements; "
            f"check the hint patterns"
        )


def test_timeline_requirement_routes_to_gantt(extracted) -> None:
    timeline = [r for r in extracted if "implementation timeline" in r.text.lower()]
    assert timeline, "the implementation timeline requirement was not extracted"
    assert any(r.deliverable_form is DeliverableForm.GANTT for r in timeline)


# --------------------------------------------------------------------------------------
# Label mapping
# --------------------------------------------------------------------------------------


def test_every_dataset_form_is_mapped(labelled) -> None:
    unmapped = {r.dataset_deliverable_form for r in labelled
                if r.dataset_deliverable_form not in DELIVERABLE_FORM_MAP}
    assert not unmapped, f"dataset forms with no contract mapping: {unmapped}"


def test_dataset_req_type_is_redundant_with_priority(labelled) -> None:
    """Documents why the contract's req_type is derived rather than adopted.

    If these two fields ever stop being perfectly correlated, the dataset's req_type
    has started carrying information and this decision should be revisited.
    """
    pairs = {(r.dataset_req_type, r.priority.value) for r in labelled}
    assert pairs == {
        ("SHALL_REQUIREMENT", "MANDATORY"),
        ("SHOULD_REQUIREMENT", "WEIGHTED"),
        ("MAY_REQUIREMENT", "NICE_TO_HAVE"),
    }, f"dataset req_type and priority are no longer 1:1: {sorted(pairs)}"


# --------------------------------------------------------------------------------------
# The LLM pass is additive
# --------------------------------------------------------------------------------------


def test_llm_pass_is_skipped_cleanly_without_a_provider(tree, monkeypatch) -> None:
    """A provider outage must not reduce what the cue pass found."""
    extractor = RequirementExtractor(use_llm=True)
    monkeypatch.setattr(
        extractor, "_get_provider",
        lambda: (_ for _ in ()).throw(RuntimeError("no provider")),
    )
    assert len(extractor.extract(tree)) == len(
        RequirementExtractor(use_llm=False).extract(tree)
    )


@pytest.mark.live
def test_llm_pass_only_adds(tree, labelled) -> None:
    cue_only = RequirementExtractor(use_llm=False).extract(tree)
    both = RequirementExtractor(use_llm=True).extract(tree)
    assert len(both) >= len(cue_only)

    # MANDATORY recall must not fall when the model joins in.
    mandatory = [r for r in labelled if r.priority is Priority.MANDATORY]
    assert all(_match(r.text, both) for r in mandatory)
