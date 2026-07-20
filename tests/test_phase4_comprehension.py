"""Phase 4 acceptance test — A3 Buyer Intelligence and A4 Bid Qualifier.

Gate: the buyer profile extracts the disclosed evaluation weights, the audience and the
decision constraints from RFP-A; the qualifier returns the labelled verdict on all six
deal contexts in data/eval/deal_contexts.json with the driving factors named.

Both gated runs are deterministic. The buyer profile's interpretive fields (audience
inference, pains, tone) need a model and are tested under the `live` marker; the facts
the profile is gated on -- weights, constraints, submission rules -- are parsed, never
generated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.buyer_intel import BuyerIntelligence
from src.agents.qualifier import (
    NO_BID_WINRATE,
    PRICE_PRESSURE_RATIO,
    BidQualifier,
    DealContext,
)
from src.agents.structurer import Structurer
from src.models.schemas import BidVerdict

ROOT = Path(__file__).parent.parent
RFP_A = ROOT / "data" / "incoming" / "RFP-A_questionnaire_nbfc.md"
DEALS = ROOT / "data" / "eval" / "deal_contexts.json"


@pytest.fixture(scope="module")
def tree():
    return Structurer(use_llm=False).parse(RFP_A)


@pytest.fixture(scope="module")
def profile(tree):
    return BuyerIntelligence(use_llm=False).profile(tree)


@pytest.fixture(scope="module")
def cases():
    raw = json.loads(DEALS.read_text(encoding="utf-8"))["deal_contexts"]
    return [(DealContext.from_dict(d), d["bid_decision"]) for d in raw]


# --------------------------------------------------------------------------------------
# A3 Buyer Intelligence
# --------------------------------------------------------------------------------------


def test_disclosed_evaluation_weights_are_extracted(profile) -> None:
    """A wrong weight misdirects the emphasis of every section downstream."""
    got = {c.name.lower(): c.weight for c in profile.evaluation_criteria}
    for name, weight in [
        ("technical solution", 35.0), ("implementation approach", 20.0),
        ("team expertise", 15.0), ("cost", 20.0), ("references", 10.0),
    ]:
        assert name in got, f"criterion {name!r} not extracted; found {sorted(got)}"
        assert got[name] == weight, f"{name}: weight {got[name]}, expected {weight}"


def test_evaluation_weights_sum_to_one_hundred(profile) -> None:
    disclosed = [c.weight for c in profile.evaluation_criteria
                 if c.weight is not None and c.name.lower() in {
                     "technical solution", "implementation approach", "team expertise",
                     "cost", "references"}]
    assert sum(disclosed) == 100.0


def test_audience_is_named(profile) -> None:
    blob = " ".join(profile.audience_roles).lower()
    assert "akshaya finance" in blob, f"issuer not identified: {profile.audience_roles}"
    assert "committee" in blob, f"evaluating body not identified: {profile.audience_roles}"


def test_decision_constraints_are_extracted(profile) -> None:
    """The regulatory and availability limits a response must respect."""
    blob = " ".join(profile.decision_constraints).lower()
    for term in ["rbi", "99.95", "data protection"]:
        assert term in blob, f"constraint {term!r} missing from profile"


def test_submission_rules_are_captured(profile) -> None:
    blob = " ".join(profile.submission_rules).lower()
    assert profile.submission_rules
    for term in ["pdf", "xlsx", "april 30"]:
        assert term in blob, f"submission rule {term!r} missing"


def test_red_lines_capture_pass_fail_language(profile) -> None:
    blob = " ".join(profile.red_lines).lower()
    assert "pass" in blob, f"pass/fail scoring not flagged as a red line: {profile.red_lines}"


def test_profile_is_usable_without_a_model(profile) -> None:
    """A3 feeds every downstream prompt; it must not require a provider to exist."""
    assert profile.evaluation_criteria
    assert profile.decision_constraints
    assert profile.tone_register == "professional"


def test_requirement_ids_are_not_mistaken_for_criteria(profile) -> None:
    names = [c.name for c in profile.evaluation_criteria]
    assert not [n for n in names if n.startswith("R-")], (
        f"numbered requirements leaked into evaluation criteria: {names}"
    )


# --------------------------------------------------------------------------------------
# A4 Bid Qualifier — the gate
# --------------------------------------------------------------------------------------


def test_all_labelled_verdicts_are_reproduced(cases) -> None:
    q = BidQualifier()
    wrong = []
    for deal, expected in cases:
        got = q.assess(deal).verdict.value
        if got != expected:
            wrong.append((deal.scenario_id, expected, got))
    assert not wrong, f"verdict mismatches (id, expected, got): {wrong}"


def test_opposite_verdicts_are_produced(cases) -> None:
    """The plan's gate: crafted contexts must diverge, not all land on one answer."""
    verdicts = {BidQualifier().assess(d).verdict for d, _ in cases}
    assert len(verdicts) >= 3, f"qualifier is not discriminating: {verdicts}"
    assert BidVerdict.BID in verdicts and BidVerdict.NO_BID in verdicts


def test_every_verdict_names_its_drivers(cases) -> None:
    for deal, _ in cases:
        assessment = BidQualifier().assess(deal)
        assert assessment.driving_factors, f"{deal.scenario_id} returned no drivers"
        assert all(f.strip() for f in assessment.driving_factors)


def test_no_bid_explains_itself(cases) -> None:
    q = BidQualifier()
    for deal, expected in cases:
        if expected != "NO_BID":
            continue
        drivers = " ".join(q.assess(deal).driving_factors).lower()
        assert "late entry" in drivers or "below the 20% floor" in drivers, (
            f"{deal.scenario_id} declined without naming a reason: {drivers}"
        )


def test_verdicts_are_stable_under_weight_perturbation(cases) -> None:
    """Six scenarios cannot validate six weights. This reports the plateau width."""
    s = BidQualifier().sensitivity(cases, trials=200, jitter=0.25)
    assert s["all_correct_rate"] >= 0.95, (
        f"only {s['all_correct_rate']:.0%} of perturbed runs reproduce all six verdicts; "
        "the model is fitted to the labels rather than to the domain"
    )


# --------------------------------------------------------------------------------------
# A4 model behaviour, independent of the labelled set
# --------------------------------------------------------------------------------------


def test_low_winrate_forces_no_bid() -> None:
    hopeless = DealContext(
        scenario_id="X", fit_percentage=40, incumbent_strength="STRONG",
        relationship_depth="NEW", entry_timing="LATE", competitor_count=8,
        deal_size_ratio=1.0,
    )
    a = BidQualifier().assess(hopeless)
    assert a.verdict is BidVerdict.NO_BID
    assert a.winrate_estimate < NO_BID_WINRATE


def test_price_compression_routes_to_partner_not_refusal() -> None:
    """Severe discounting reduces the value of winning, not the chance of it."""
    squeezed = DealContext(
        scenario_id="X", fit_percentage=90, incumbent_strength="NONE",
        relationship_depth="DEEP", entry_timing="EARLY", competitor_count=2,
        deal_size_ratio=PRICE_PRESSURE_RATIO,
    )
    a = BidQualifier().assess(squeezed)
    assert a.verdict is BidVerdict.PARTNER_BID
    assert a.winrate_estimate >= NO_BID_WINRATE, "a partner bid is still winnable"


def test_deep_relationship_reads_incumbency_as_ours() -> None:
    """A strong incumbent alongside a deep relationship is us, not a threat."""
    ours = DealContext(
        scenario_id="X", fit_percentage=90, incumbent_strength="STRONG",
        relationship_depth="DEEP", entry_timing="EARLY", competitor_count=2,
    )
    theirs = DealContext(
        scenario_id="Y", fit_percentage=90, incumbent_strength="STRONG",
        relationship_depth="NEW", entry_timing="EARLY", competitor_count=2,
    )
    q = BidQualifier()
    assert q.assess(ours).winrate_estimate > q.assess(theirs).winrate_estimate
    assert any("incumbency" in f for f in q.assess(ours).driving_factors)


def test_late_entry_against_incumbent_is_penalised_sharply() -> None:
    early = DealContext(scenario_id="X", fit_percentage=80, incumbent_strength="STRONG",
                        relationship_depth="MODERATE", entry_timing="EARLY",
                        competitor_count=3)
    late = DealContext(scenario_id="Y", fit_percentage=80, incumbent_strength="STRONG",
                       relationship_depth="MODERATE", entry_timing="LATE",
                       competitor_count=3)
    q = BidQualifier()
    assert q.assess(late).winrate_estimate < 0.5 * q.assess(early).winrate_estimate


def test_unviable_fit_is_declined_whatever_the_relationship() -> None:
    """A warm relationship cannot make an unresponsive bid responsive."""
    a = BidQualifier().assess(DealContext(
        scenario_id="X", fit_percentage=30, incumbent_strength="NONE",
        relationship_depth="DEEP", entry_timing="EARLY", competitor_count=1,
    ))
    assert a.verdict is BidVerdict.NO_BID
    assert any("viable floor" in f for f in a.driving_factors)


def test_more_competitors_never_helps() -> None:
    q = BidQualifier()
    rates = [
        q.assess(DealContext(scenario_id=str(n), fit_percentage=85,
                             incumbent_strength="WEAK", relationship_depth="MODERATE",
                             entry_timing="EARLY", competitor_count=n)).winrate_estimate
        for n in range(2, 9)
    ]
    assert rates == sorted(rates, reverse=True), f"winrate not monotonic in field size: {rates}"


def test_effort_scales_with_scope() -> None:
    q = BidQualifier()
    small = q.assess(DealContext(scenario_id="s", fit_percentage=80, competitor_count=2,
                                 deal_size_ratio=0.8))
    large = q.assess(DealContext(scenario_id="l", fit_percentage=80, competitor_count=6,
                                 deal_size_ratio=1.5))
    assert large.effort_estimate_hours > small.effort_estimate_hours


def test_qualifier_makes_no_model_call() -> None:
    """CLAUDE.md: deterministic components contain zero LLM calls."""
    source = (ROOT / "src" / "agents" / "qualifier.py").read_text(encoding="utf-8")
    for forbidden in ["provider", "generate(", "llm", "embed("]:
        assert forbidden not in source.lower().replace("no llm call", ""), (
            f"qualifier.py references {forbidden!r}; it must stay deterministic"
        )


# --------------------------------------------------------------------------------------
# Interpretive fields need a model
# --------------------------------------------------------------------------------------


@pytest.mark.live
def test_enrichment_adds_pains_without_losing_parsed_facts(tree) -> None:
    parsed = BuyerIntelligence(use_llm=False).profile(tree)
    enriched = BuyerIntelligence(use_llm=True).profile(tree)

    assert enriched.stated_pains, "no pains inferred"
    assert len(enriched.audience_roles) >= len(parsed.audience_roles)
    # Parsed facts must survive the model pass untouched.
    assert enriched.evaluation_criteria == parsed.evaluation_criteria
    assert enriched.decision_constraints == parsed.decision_constraints
