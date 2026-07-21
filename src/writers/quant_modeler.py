"""Quantitative modeler — Phase 8. DETERMINISTIC: zero LLM calls.

Handles COSTING. Takes program parameters (duration, phases, FTE curve, blended rate,
contingency %) and computes phase costs, the services/software/cloud/contingency split,
a reconciled total, the FTE ramp and an indicative payback.

Everything here is arithmetic, so a model has no place in it. A model asked to total a
cost table will produce a number that looks right, and a proposal whose figures do not
add up is the single most damaging error a bid can contain -- it is the one thing a
procurement analyst will definitely check.

`reconciles()` is the contract: components must sum to the stated total exactly, to the
rupee. The consistency checker in Phase 9 re-derives the same sums independently, so a
mistake here is caught twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.models.schemas import (
    GeneratedSection,
    OutlineSection,
    ProvenanceKind,
    SectionStatus,
)
from src.utils import provenance

WORKING_DAYS_PER_WEEK = 5
MONTHS_PER_WEEK = 12 / 52


@dataclass
class PhaseCost:
    name: str
    weeks: int
    fte: int
    person_days: int
    services_cost: float
    start_week: int
    end_week: int


@dataclass
class CostModel:
    """A fully reconciled programme cost model. Every figure is derived, none asserted."""

    currency: str
    phases: list[PhaseCost] = field(default_factory=list)
    services: float = 0.0
    software: float = 0.0
    cloud: float = 0.0
    training: float = 0.0
    programme_management: float = 0.0
    contingency: float = 0.0
    contingency_pct: float = 0.0
    total: float = 0.0
    total_weeks: int = 0
    peak_fte: int = 0
    average_fte: float = 0.0
    day_rate: float = 0.0
    milestones: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return (self.services + self.software + self.cloud + self.training
                + self.programme_management)

    @property
    def components(self) -> dict[str, float]:
        return {
            "Professional services": self.services,
            "Software subscription": self.software,
            "Cloud infrastructure": self.cloud,
            "Training and enablement": self.training,
            "Programme management": self.programme_management,
            "Contingency": self.contingency,
        }

    def reconciles(self) -> bool:
        """Components must sum to the stated total. Exactly."""
        return abs(sum(self.components.values()) - self.total) < 0.01

    def phase_costs_reconcile(self) -> bool:
        return abs(sum(p.services_cost for p in self.phases) - self.services) < 0.01

    def durations_reconcile(self) -> bool:
        return sum(p.weeks for p in self.phases) == self.total_weeks

    def payback_months(self, annual_benefit: float) -> float | None:
        """Indicative payback. None when no benefit figure is supplied.

        Deliberately returns None rather than a default: an invented benefit produces an
        invented payback, and payback is exactly the number a CFO will interrogate.
        """
        if not annual_benefit or annual_benefit <= 0:
            return None
        return round(self.total / (annual_benefit / 12.0), 1)


class QuantModeler:
    """Builds a cost model and renders it. One public method: write()."""

    def __init__(self, settings=None, currency: str = "INR") -> None:
        if settings is None:
            from config import get_settings

            settings = get_settings()
        self.settings = settings
        self.currency = currency.upper()

    # --- public ---------------------------------------------------------------------

    def write(
        self,
        section: OutlineSection,
        params: dict[str, Any] | None = None,
        profile: str = "standard",
        annual_benefit: float | None = None,
    ) -> GeneratedSection:
        model = self.build(params or self.load_params(profile))
        content = self.render(section.title, model, annual_benefit)
        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, ProvenanceKind.COMPUTED
            ),
            status=SectionStatus.DRAFTED,
        )

    def load_params(self, profile: str = "standard") -> dict[str, Any]:
        import yaml

        path = Path(self.settings.data_path) / "params" / f"programme_{profile}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"no programme parameters at {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    # --- model ----------------------------------------------------------------------

    def build(self, params: dict[str, Any]) -> CostModel:
        cost_params = params.get("cost_parameters", {})
        suffix = self.currency.lower()
        day_rate = float(cost_params.get(f"blended_day_rate_{suffix}", 0))
        if not day_rate:
            raise ValueError(f"no blended day rate for currency {self.currency}")

        phases: list[PhaseCost] = []
        week_cursor = 0
        for entry in params.get("phases", []):
            weeks = int(entry["weeks"])
            fte = int(entry["fte"])
            person_days = weeks * WORKING_DAYS_PER_WEEK * fte
            phases.append(PhaseCost(
                name=str(entry["name"]).replace("_", " "),
                weeks=weeks,
                fte=fte,
                person_days=person_days,
                services_cost=person_days * day_rate,
                start_week=week_cursor,
                end_week=week_cursor + weeks,
            ))
            week_cursor += weeks

        services = sum(p.services_cost for p in phases)
        software = float(cost_params.get(f"software_subscription_{suffix}", 0))
        cloud = float(cost_params.get(f"cloud_{suffix}", 0))
        training = float(cost_params.get(f"additional_training_{suffix}", 0))
        programme = float(cost_params.get(f"program_management_{suffix}", 0))

        contingency_pct = float(cost_params.get("contingency_pct", 0))
        subtotal = services + software + cloud + training + programme
        contingency = round(subtotal * contingency_pct / 100.0, 2)

        model = CostModel(
            currency=self.currency,
            phases=phases,
            services=services,
            software=software,
            cloud=cloud,
            training=training,
            programme_management=programme,
            contingency=contingency,
            contingency_pct=contingency_pct,
            total=round(subtotal + contingency, 2),
            total_weeks=week_cursor,
            peak_fte=max((p.fte for p in phases), default=0),
            average_fte=round(
                sum(p.fte * p.weeks for p in phases) / week_cursor, 1
            ) if week_cursor else 0.0,
            day_rate=day_rate,
            milestones=list(params.get("milestones", [])),
            assumptions=list(params.get("assumptions", [])),
        )

        if not model.reconciles():
            raise AssertionError(
                f"cost model does not reconcile: components "
                f"{sum(model.components.values()):.2f} vs total {model.total:.2f}"
            )
        return model

    # --- rendering ------------------------------------------------------------------

    def render(self, title: str, model: CostModel, annual_benefit: float | None = None
               ) -> str:
        symbol = "₹" if model.currency == "INR" else "€"
        lines = [f"## {title}", ""]

        lines += [
            f"The programme runs {model.total_weeks} weeks "
            f"({model.total_weeks * MONTHS_PER_WEEK:.1f} months) across "
            f"{len(model.phases)} phases, peaking at {model.peak_fte} FTE and averaging "
            f"{model.average_fte} FTE.",
            "",
            "### Phase effort and cost",
            "",
            "| Phase | Weeks | FTE | Person-days | Services cost |",
            "|---|---|---|---|---|",
        ]
        for phase in model.phases:
            lines.append(
                f"| {phase.name} | {phase.weeks} | {phase.fte} | {phase.person_days:,} "
                f"| {symbol}{phase.services_cost:,.0f} |"
            )
        lines.append(
            f"| **Total** | **{model.total_weeks}** | **{model.peak_fte} peak** "
            f"| **{sum(p.person_days for p in model.phases):,}** "
            f"| **{symbol}{model.services:,.0f}** |"
        )

        lines += [
            "",
            "### Investment breakdown",
            "",
            "| Component | Amount | Share |",
            "|---|---|---|",
        ]
        for name, amount in model.components.items():
            share = (amount / model.total * 100) if model.total else 0.0
            lines.append(f"| {name} | {symbol}{amount:,.0f} | {share:.1f}% |")
        lines.append(f"| **Total investment** | **{symbol}{model.total:,.0f}** | **100.0%** |")

        lines += [
            "",
            f"Contingency is held at {model.contingency_pct:.0f}% of the "
            f"{symbol}{model.subtotal:,.0f} subtotal, released against named risks rather "
            f"than as a general pool.",
            f"Services are priced at a blended day rate of {symbol}{model.day_rate:,.0f}.",
        ]

        if model.milestones:
            lines += [
                "",
                "### Milestone payment schedule",
                "",
                "| Milestone | Week | Deliverable | Payment |",
                "|---|---|---|---|",
            ]
            for milestone in model.milestones:
                pct = float(milestone.get("payment_pct", 0))
                lines.append(
                    f"| {milestone.get('name', '')} | {milestone.get('week', '')} "
                    f"| {milestone.get('deliverable', '')} | {pct:.0f}% "
                    f"({symbol}{model.total * pct / 100:,.0f}) |"
                )
            total_pct = sum(float(m.get("payment_pct", 0)) for m in model.milestones)
            lines.append(f"| **Total** | | | **{total_pct:.0f}%** |")

        payback = model.payback_months(annual_benefit or 0)
        if payback is not None:
            lines += [
                "",
                f"At a stated annual benefit of {symbol}{annual_benefit:,.0f}, indicative "
                f"payback is {payback} months from go-live.",
            ]

        return "\n".join(lines) + "\n"
