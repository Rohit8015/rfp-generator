"""Phase 6 acceptance test — A5 Win Themes, A6 Response Architect, A7 Proof Matcher.

Gate: zero orphan requirements in the outline; every surviving theme maps to >=2
requirements and >=1 proof; the GAP list is produced.

All three agents run deterministically here. A5 needs a model only to phrase a theme;
whether a theme survives is measured in Python, so the gate does not depend on a
generation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.architect import ResponseArchitect, compliance_skeleton
from src.agents.buyer_intel import BuyerIntelligence
from src.agents.proofs import ProofMatcher, gap_requirement_ids
from src.agents.requirements import RequirementExtractor
from src.agents.structurer import Structurer
from src.agents.win_themes import MIN_REQUIREMENTS_PER_THEME, WinThemeGenerator
from src.models.schemas import (
    BuyerProfile,
    DeliverableForm,
    EvalCriterion,
    Fit,
    OutlineMode,
    Priority,
    ReqType,
    Requirement,
)

ROOT = Path(__file__).parent.parent
RFP_A = ROOT / "data" / "incoming" / "RFP-A_questionnaire_nbfc.md"


@pytest.fixture(scope="module")
def pipeline():
    tree = Structurer(use_llm=False).parse(RFP_A)
    reqs = RequirementExtractor(use_llm=False).extract(tree)
    buyer = BuyerIntelligence(use_llm=False).profile(tree)
    proofs = ProofMatcher.load_library()
    return tree, reqs, buyer, proofs


@pytest.fixture(scope="module")
def matches(pipeline):
    _, reqs, _, proofs = pipeline
    return ProofMatcher(proofs).match(reqs)


@pytest.fixture(scope="module")
def themes(pipeline):
    _, reqs, buyer, proofs = pipeline
    return WinThemeGenerator(use_llm=False).generate(buyer, reqs, proofs)


@pytest.fixture(scope="module")
def outline(pipeline, themes):
    _, reqs, buyer, _ = pipeline
    return ResponseArchitect().design(reqs, buyer, themes)


def _req(rid: str, text: str, **kw) -> Requirement:
    return Requirement(
        id=rid, source_section=kw.get("section", "1"), text=text,
        req_type=kw.get("req_type", ReqType.SHALL_REQUIREMENT),
        priority=kw.get("priority", Priority.MANDATORY),
        deliverable_form=kw.get("form", DeliverableForm.PROSE),
    )


# --------------------------------------------------------------------------------------
# A7 Proof Matcher — the GAP rule
# --------------------------------------------------------------------------------------


def test_every_requirement_is_classified(pipeline, matches) -> None:
    _, reqs, _, _ = pipeline
    assert len(matches) == len(reqs)
    assert {m.requirement_id for m in matches} == {r.id for r in reqs}


def test_gap_list_is_produced_and_non_trivial(matches) -> None:
    """A library that covers everything would mean the matcher is not discriminating."""
    gaps = gap_requirement_ids(matches)
    assert gaps, "no GAPs at all: the matcher is matching indiscriminately"
    assert len(gaps) < len(matches), "everything is a GAP: the matcher is not matching"


def test_a_gap_never_cites_proof(matches) -> None:
    """CLAUDE.md: never invent a proof point to fill a GAP."""
    for m in matches:
        if m.fit is Fit.GAP:
            assert m.proof_ids == []
        else:
            assert m.proof_ids, f"{m.requirement_id} is {m.fit.value} with no proof"


def test_unmatchable_requirement_returns_gap(pipeline) -> None:
    _, _, _, proofs = pipeline
    weird = _req("R-999", "The vendor shall supply trained alpacas for the reception area.")
    match = ProofMatcher(proofs).match([weird])[0]
    assert match.fit is Fit.GAP
    assert "no proof point" in match.rationale


def test_every_match_explains_itself(matches) -> None:
    assert all(m.rationale.strip() for m in matches)


def test_matcher_makes_no_generative_call() -> None:
    """A7 may measure, but must never ask a model for a judgement.

    It uses the LOCAL cross-encoder to score relevance, which is a measurement. It must
    not call generate(): a model asked "does this proof support this requirement?"
    answers yes far too readily, and a false STRONG puts an unevidenced claim in front
    of a client.
    """
    source = (ROOT / "src" / "agents" / "proofs.py").read_text(encoding="utf-8").lower()
    assert ".generate(" not in source, "proofs.py makes a generative call"
    assert "generate_many" not in source, "proofs.py makes a generative call"


def test_matcher_degrades_to_lexical_without_a_reranker(pipeline) -> None:
    """No provider means a worse matcher, not a crashed one."""
    _, reqs, _, proofs = pipeline
    matches = ProofMatcher(proofs, use_embeddings=False).match(reqs[:10])
    assert len(matches) == 10
    assert all(m.rationale for m in matches)


def test_cross_encoder_separates_covered_from_uncovered(pipeline) -> None:
    """The library covers fraud detection and RBI compliance; it has nothing on
    multilingual UI, AR/VR, gamification or social listening.
    """
    _, reqs, _, proofs = pipeline
    matches = {m.requirement_id: m for m in ProofMatcher(proofs).match(reqs)}

    def fit_for(fragment: str):
        # Single-topic requirements only. The extractor also emits one blob holding the
        # whole weighted-requirements table, which spans many topics at once and is
        # rightly PARTIAL against almost anything.
        found = [r for r in reqs
                 if fragment.lower() in r.text.lower() and len(r.text) < 130]
        return [matches[r.id].fit for r in found]

    for fragment in ["social media listening", "multi-lingual", "gamification", "AR/VR"]:
        fits = fit_for(fragment)
        assert fits, f"no requirement mentioning {fragment!r}"
        assert all(f is Fit.GAP for f in fits), (
            f"{fragment!r} should be a GAP: the library has no such proof, got {fits}"
        )

    for fragment in ["RBI guidelines", "fraud detection"]:
        fits = fit_for(fragment)
        assert fits and all(f is not Fit.GAP for f in fits), (
            f"{fragment!r} should be evidenced, got {fits}"
        )


# --------------------------------------------------------------------------------------
# A5 Win Themes — the two-requirement rule
# --------------------------------------------------------------------------------------


def test_surviving_themes_thread_at_least_two_requirements(themes) -> None:
    for theme in WinThemeGenerator.surviving(themes):
        assert len(theme.requirement_ids_covered) >= MIN_REQUIREMENTS_PER_THEME
        assert theme.proof_ids, f"{theme.id} survives with no proof"


def test_dropped_themes_record_why(themes) -> None:
    for theme in themes:
        if theme.dropped:
            assert theme.drop_reason, f"{theme.id} dropped with no reason logged"


def test_at_most_five_themes_survive(themes) -> None:
    assert len(WinThemeGenerator.surviving(themes)) <= 5


def test_seller_side_theme_is_dropped(pipeline) -> None:
    """Themes are buyer-side. 'We are a leader in X' is decorative by definition."""
    _, reqs, buyer, proofs = pipeline
    gen = WinThemeGenerator(use_llm=False)
    from src.agents.win_themes import _ThemeDraft

    theme = gen._verify(
        "T-99",
        _ThemeDraft(statement="We are a leading provider of digital transformation.",
                    buyer_pain_addressed="none"),
        reqs, proofs,
    )
    assert theme.dropped
    assert "seller-side" in theme.drop_reason


def test_decorative_theme_is_dropped_not_padded(pipeline) -> None:
    _, _, _, proofs = pipeline
    from src.agents.win_themes import _ThemeDraft

    lone = [_req("R-001", "The vendor shall supply trained alpacas to reception.")]
    theme = WinThemeGenerator(use_llm=False)._verify(
        "T-98",
        _ThemeDraft(statement="your reception is staffed by trained alpacas throughout",
                    buyer_pain_addressed="reception"),
        lone, proofs,
    )
    assert theme.dropped
    assert "decorative" in theme.drop_reason or "no proof" in theme.drop_reason


# --------------------------------------------------------------------------------------
# A6 Response Architect — the orphan gate
# --------------------------------------------------------------------------------------


def test_zero_orphan_requirements(pipeline, outline) -> None:
    """The phase gate. Every requirement lands somewhere."""
    _, reqs, _, _ = pipeline
    orphans = outline.orphans([r.id for r in reqs])
    assert not orphans, f"requirements left unplaced: {orphans}"


def test_each_requirement_has_exactly_one_primary_section(pipeline, outline) -> None:
    _, reqs, _, _ = pipeline
    placements: dict[str, list[str]] = {}
    for section in outline.sections:
        for rid in section.requirement_ids:
            placements.setdefault(rid, []).append(section.id)
    duplicated = {k: v for k, v in placements.items() if len(v) > 1}
    assert not duplicated, f"requirements placed twice: {duplicated}"
    assert len(placements) == len(reqs)


def test_sections_are_ordered_and_identified(outline) -> None:
    assert [s.order_index for s in outline.sections] == list(range(len(outline.sections)))
    assert len({s.id for s in outline.sections}) == len(outline.sections)
    assert all(s.title.strip() and s.purpose.strip() for s in outline.sections)


def test_compliance_mode_mirrors_the_buyer_structure(pipeline) -> None:
    _, reqs, buyer, _ = pipeline
    outline = ResponseArchitect().design(reqs, buyer, [], mode=OutlineMode.COMPLIANCE)
    titles = " ".join(s.title for s in outline.sections)
    assert "2.1" in titles and "4" in titles
    assert not outline.orphans([r.id for r in reqs])


def test_narrative_mode_uses_the_consulting_spine(pipeline) -> None:
    _, reqs, buyer, _ = pipeline
    outline = ResponseArchitect().design(reqs, buyer, [], mode=OutlineMode.NARRATIVE)
    titles = [s.title for s in outline.sections]
    assert "Executive summary" in titles
    assert any("approach" in t.lower() for t in titles)
    assert not outline.orphans([r.id for r in reqs])


def test_mode_is_chosen_from_submission_rules() -> None:
    demanding = BuyerProfile(submission_rules=[
        "Responses must follow the prescribed format in Annexure B.",
    ])
    open_brief = BuyerProfile(submission_rules=["Send us your best thinking."])
    assert ResponseArchitect.choose_mode(demanding) is OutlineMode.COMPLIANCE
    assert ResponseArchitect.choose_mode(open_brief) is OutlineMode.NARRATIVE


def test_themes_are_carried_into_sections_holding_their_requirements(outline, themes
                                                                     ) -> None:
    surviving = {t.id for t in WinThemeGenerator.surviving(themes)}
    if not surviving:
        pytest.skip("no themes survived on this input")
    carried = {tid for s in outline.sections for tid in s.themes_to_carry}
    assert carried <= surviving, "a dropped theme is being carried into a section"
    assert carried, "no section carries any theme"


def test_costing_requirement_lands_in_commercials(pipeline) -> None:
    _, _, buyer, _ = pipeline
    reqs = [
        _req("R-001", "The vendor shall submit a detailed pricing schedule.",
             form=DeliverableForm.COSTING),
        _req("R-002", "The vendor shall describe the solution architecture."),
        _req("R-003", "The vendor shall provide an implementation timeline with "
                      "milestones.", form=DeliverableForm.GANTT),
    ]
    outline = ResponseArchitect().design(reqs, buyer, [], mode=OutlineMode.NARRATIVE)
    placement = {rid: s.title for s in outline.sections for rid in s.requirement_ids}
    assert "Commercial" in placement["R-001"]
    assert "timeline" in placement["R-003"].lower()


def test_unclassifiable_requirement_still_lands_somewhere(pipeline) -> None:
    """The catch-all is what makes the zero-orphan guarantee structural."""
    _, _, buyer, _ = pipeline
    odd = [_req("R-001", "Zzyzx qqqq wibble frobnicate."),
           _req("R-002", "Blorp gnnk splunge.")]
    outline = ResponseArchitect().design(odd, buyer, [], mode=OutlineMode.NARRATIVE)
    assert not outline.orphans([r.id for r in odd])


def test_compliance_skeleton_traces_every_requirement(pipeline, outline) -> None:
    """The outline is the compliance matrix skeleton, per the plan."""
    _, reqs, _, _ = pipeline
    rows = compliance_skeleton(outline, reqs)
    assert len(rows) == len(reqs)
    assert all(r["section_id"] for r in rows), "a requirement has no section anchor"
    assert rows[0]["priority"] == Priority.MANDATORY.value, "mandatory rows come first"


def test_architect_makes_no_model_call() -> None:
    source = (ROOT / "src" / "agents" / "architect.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ["get_provider", "generate(", "embed("]:
        assert forbidden not in lowered, f"architect.py calls {forbidden}"


# --------------------------------------------------------------------------------------
# With a model in the loop
# --------------------------------------------------------------------------------------


@pytest.mark.live
def test_generated_themes_are_buyer_side_and_verified(pipeline) -> None:
    _, reqs, buyer, proofs = pipeline
    buyer = buyer.model_copy(update={"stated_pains": [
        "Customer onboarding takes too long and loses applicants",
        "Manual underwriting cannot scale with volume",
        "Regulatory reporting is assembled by hand each quarter",
    ]})
    themes = WinThemeGenerator(use_llm=True).generate(buyer, reqs, proofs)
    surviving = WinThemeGenerator.surviving(themes)
    assert surviving, "no theme survived verification"
    for theme in surviving:
        assert len(theme.requirement_ids_covered) >= MIN_REQUIREMENTS_PER_THEME
        assert theme.proof_ids
        assert not theme.statement.lower().startswith("we ")
