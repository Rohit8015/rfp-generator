"""Phase 8 acceptance test — quantitative modeler and visual generator.

Gate: charts render to PNG, cost components sum to the stated total, and neither module
makes a model call.

The reconciliation tests matter more than they look. A proposal whose figures do not add
up is the one error a procurement analyst will certainly find, and it discredits
everything else in the document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.schemas import (
    DeliverableForm,
    OutlineSection,
    ProvenanceKind,
    SectionStatus,
)
from src.utils import provenance
from src.writers.quant_modeler import QuantModeler
from src.writers.visual_generator import VisualGenerator

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def modeler():
    return QuantModeler(currency="INR")


@pytest.fixture(scope="module")
def model(modeler):
    return modeler.build(modeler.load_params("standard"))


def _section(title="Commercials", form=DeliverableForm.COSTING) -> OutlineSection:
    return OutlineSection(id="S-09", order_index=8, title=title,
                          purpose="Investment and pricing", deliverable_form=form)


# --------------------------------------------------------------------------------------
# The cost model must reconcile
# --------------------------------------------------------------------------------------


def test_components_sum_to_the_stated_total(model) -> None:
    assert model.reconciles(), (
        f"components {sum(model.components.values()):,.2f} != total {model.total:,.2f}"
    )
    assert abs(sum(model.components.values()) - model.total) < 0.01


def test_phase_costs_sum_to_the_services_line(model) -> None:
    assert model.phase_costs_reconcile()


def test_phase_durations_sum_to_the_programme_duration(model) -> None:
    assert model.durations_reconcile()
    assert model.total_weeks == 72


def test_contingency_is_a_percentage_of_the_subtotal(model) -> None:
    expected = round(model.subtotal * model.contingency_pct / 100.0, 2)
    assert abs(model.contingency - expected) < 0.01
    assert model.contingency_pct > 0


def test_peak_and_average_fte_are_derived_not_asserted(model) -> None:
    assert model.peak_fte == max(p.fte for p in model.phases)
    weighted = sum(p.fte * p.weeks for p in model.phases) / model.total_weeks
    assert abs(model.average_fte - round(weighted, 1)) < 0.05


def test_person_days_follow_a_five_day_week(model) -> None:
    for phase in model.phases:
        assert phase.person_days == phase.weeks * 5 * phase.fte


def test_phases_are_contiguous(model) -> None:
    """A gap or overlap between phases would make the Gantt lie."""
    cursor = 0
    for phase in model.phases:
        assert phase.start_week == cursor
        cursor = phase.end_week
    assert cursor == model.total_weeks


def test_a_broken_model_refuses_to_build(modeler) -> None:
    """Reconciliation is enforced at build time, not left to a later check."""
    params = modeler.load_params("standard")
    params["cost_parameters"]["blended_day_rate_inr"] = 0
    with pytest.raises(ValueError, match="no blended day rate"):
        modeler.build(params)


def test_payback_is_none_without_a_benefit_figure(model) -> None:
    """An invented benefit produces an invented payback. Return nothing instead."""
    assert model.payback_months(0) is None
    assert model.payback_months(model.total) == pytest.approx(12.0, rel=0.01)


def test_all_currency_profiles_reconcile() -> None:
    for profile in ["small", "standard", "large"]:
        for currency in ["INR", "EUR"]:
            modeler = QuantModeler(currency=currency)
            model = modeler.build(modeler.load_params(profile))
            assert model.reconciles(), f"{profile}/{currency} does not reconcile"
            assert model.durations_reconcile(), f"{profile}/{currency} duration mismatch"


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def test_rendered_section_is_computed_provenance(modeler) -> None:
    section = modeler.write(_section())
    assert section.status is SectionStatus.DRAFTED
    assert section.sentences
    assert all(r.kind is ProvenanceKind.COMPUTED for r in section.sentences)
    assert all(not r.source_ids for r in section.sentences)
    provenance.verify_complete(section)


def test_rendered_totals_match_the_model(modeler, model) -> None:
    content = modeler.render("Commercials", model)
    assert f"{model.total:,.0f}" in content, "the stated total is not the computed total"
    assert f"{model.services:,.0f}" in content
    for phase in model.phases:
        assert phase.name in content


def test_milestone_payments_sum_to_one_hundred_percent(model) -> None:
    total = sum(float(m.get("payment_pct", 0)) for m in model.milestones)
    assert abs(total - 100.0) < 0.01, f"milestone payments sum to {total}%"


# --------------------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def visuals(tmp_path_factory):
    from config import Settings

    out = tmp_path_factory.mktemp("charts")
    return VisualGenerator(Settings(output_dir=out))


def _rendered(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 5000


def test_gantt_renders(visuals, model) -> None:
    assert _rendered(visuals.gantt(model))


def test_investment_profile_renders(visuals, model) -> None:
    assert _rendered(visuals.investment_profile(model))


def test_risk_heat_map_renders(visuals) -> None:
    risks = [
        {"name": "Legacy discovery", "likelihood": "high", "impact": "high"},
        {"name": "SME availability", "likelihood": 3, "impact": 4},
        {"name": "Data quality", "likelihood": "medium", "impact": "critical"},
    ]
    assert _rendered(visuals.risk_heat_map(risks))


def test_capability_map_renders(visuals) -> None:
    caps = [
        {"name": "Digital onboarding", "current": 2, "target": 5},
        {"name": "Credit decisioning", "current": 1, "target": 4},
        {"name": "Regulatory reporting", "current": 3, "target": 5},
    ]
    assert _rendered(visuals.capability_map(caps))


def test_risk_levels_accept_words_and_numbers(visuals) -> None:
    level = VisualGenerator._level
    assert level("high") == 4 and level("Very High") == 5 and level("low") == 2
    assert level(3) == 3 and level(99) == 5 and level(-4) == 1
    assert level("nonsense") == 3, "an unknown word must not crash a render"


def test_visual_section_carries_assets_and_provenance(visuals, model) -> None:
    section = visuals.write(_section(title="Delivery plan", form=DeliverableForm.GANTT),
                            model=model,
                            risks=[{"name": "R", "likelihood": 2, "impact": 2}])
    assert len(section.asset_paths) == 3
    assert all(Path(p).is_file() for p in section.asset_paths)
    assert all(r.kind is ProvenanceKind.COMPUTED for r in section.sentences)
    provenance.verify_complete(section)


def test_visual_section_without_data_escalates(visuals) -> None:
    section = visuals.write(_section(form=DeliverableForm.CHART))
    assert section.status is SectionStatus.ESCALATED
    assert section.asset_paths == []


def test_charts_read_the_same_phases_as_the_cost_table(visuals, model, modeler) -> None:
    """A chart disagreeing with the table beside it is the classic proposal error."""
    content = modeler.render("Commercials", model)
    section = visuals.write(_section(form=DeliverableForm.GANTT), model=model)
    assert str(model.total_weeks) in section.content_md
    assert str(model.total_weeks) in content


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["quant_modeler.py", "visual_generator.py"])
def test_no_model_call_in_the_deterministic_path(module: str) -> None:
    """CLAUDE.md: these components must contain zero LLM calls."""
    source = (ROOT / "src" / "writers" / module).read_text(encoding="utf-8").lower()
    for forbidden in ["get_provider", "llmprovider", ".generate(", ".embed(", ".rerank("]:
        assert forbidden not in source, f"{module} references {forbidden}"


def test_model_is_reproducible(modeler) -> None:
    """Same parameters, same numbers. Every time."""
    a = modeler.build(modeler.load_params("standard"))
    b = modeler.build(modeler.load_params("standard"))
    assert a.total == b.total
    assert [p.services_cost for p in a.phases] == [p.services_cost for p in b.phases]
