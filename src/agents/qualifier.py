"""A4 Bid Qualifier — Phase 4.

In: a deal context (and optionally requirements + capability inventory).
Out: BidAssessment (MANDATORY fit %, GAP list, effort, winrate, BID / PARTNER_BID /
NO_BID). Deterministic factor model. Winrate below 20% forces NO_BID.

DETERMINISTIC: this module contains no LLM call, and a test asserts it.

Model shape, and where it comes from
------------------------------------
A weighted score over five factors, mapped to a win probability, plus two explicit
rules. The weights are ordinary Shipley capture practice: solution fit dominates,
relationship and incumbency next, timing after that, and raw competitor count least
because it is the crudest proxy.

The two rules are named rather than buried in weights, because each encodes a
qualitative judgement a linear model represents badly:

1. LATE entry against a STRONG incumbent that is not us. The incumbent has usually
   shaped the requirement by then and the bid is column fodder. This is a large
   multiplier, not a small weight, because the effect is not linear.

2. Severe price compression (deal size well below the normal ratio). This does not
   reduce the chance of winning, it reduces the value of winning, so it routes to
   PARTNER_BID rather than depressing the winrate.

`incumbent_strength` is ambiguous in the dataset: it does not say whose incumbent. A
DEEP relationship alongside a STRONG incumbent almost always means the incumbent is us,
so that combination is read as an advantage rather than a threat.

Honesty note: the six labelled scenarios are far too few to validate six parameters.
`sensitivity()` exists so the result can be reported with a robustness figure instead of
a bare score.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from src.models.schemas import BidAssessment, BidVerdict, Priority, Requirement

# --------------------------------------------------------------------------------------
# Factor scales. Each maps a categorical level onto 0..1, where 1 is most favourable.
# --------------------------------------------------------------------------------------

RELATIONSHIP = {"DEEP": 1.0, "MODERATE": 0.6, "LIMITED": 0.35, "NEW": 0.2}
#: Strength of the incumbent supplier, scored as a threat to us.
INCUMBENT = {"NONE": 1.0, "WEAK": 0.75, "MEDIUM": 0.45, "STRONG": 0.2}
TIMING = {"EARLY": 1.0, "MID": 0.6, "LATE": 0.2}

WEIGHTS = {
    "fit": 0.35,
    "relationship": 0.20,
    "incumbency": 0.20,
    "timing": 0.15,
    "competition": 0.10,
}

#: Maps the 0..1 factor score onto a win probability. The exponent punishes mediocrity
#: (a middling score on every factor is a weak bid, not an average one); the ceiling
#: reflects that no competitive bid is ever a certainty.
SCORE_EXPONENT = 1.5
MAX_WINRATE = 85.0

#: Rule 1. Applied when entry is LATE and a STRONG incumbent is not us.
LATE_VS_INCUMBENT_MULTIPLIER = 0.35

#: Rule 2. Deal size at or below this share of normal signals severe price compression.
PRICE_PRESSURE_RATIO = 0.6

#: Contractual floor from the plan. Below this, the verdict is NO_BID regardless.
NO_BID_WINRATE = 20.0

#: Below this MANDATORY fit we cannot be responsive, whatever the win probability says.
MIN_VIABLE_FIT = 50.0


@dataclass
class DealContext:
    """The commercial situation around a bid. Not an inter-agent contract."""

    scenario_id: str = ""
    name: str = ""
    description: str = ""
    fit_percentage: float = 0.0
    incumbent_strength: str = "NONE"
    relationship_depth: str = "NEW"
    entry_timing: str = "EARLY"
    competitor_count: int = 3
    deal_size_ratio: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> DealContext:
        return cls(
            scenario_id=d.get("scenario_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            fit_percentage=float(d.get("fit_percentage", 0)),
            incumbent_strength=str(d.get("incumbent_strength", "NONE")).upper(),
            relationship_depth=str(d.get("relationship_depth", "NEW")).upper(),
            entry_timing=str(d.get("entry_timing", "EARLY")).upper(),
            competitor_count=int(d.get("competitor_count", 3)),
            deal_size_ratio=float(d.get("deal_size_ratio", 1.0)),
        )


@dataclass
class _Factors:
    fit: float
    relationship: float
    incumbency: float
    timing: float
    competition: float
    we_are_incumbent: bool
    notes: list[str] = field(default_factory=list)


class BidQualifier:
    """Scores a deal and returns a verdict. One public method: assess()."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights or WEIGHTS)

    # --- public ---------------------------------------------------------------------

    def assess(
        self,
        deal: DealContext,
        requirements: list[Requirement] | None = None,
        capabilities: set[str] | None = None,
    ) -> BidAssessment:
        """Return a BidAssessment with the driving factors named."""
        fit_pct, gaps = self._mandatory_fit(deal, requirements, capabilities)
        factors = self._factors(deal, fit_pct)
        winrate = self._winrate(deal, factors)
        verdict, drivers = self._verdict(deal, factors, winrate, fit_pct)

        return BidAssessment(
            mandatory_fit_pct=round(fit_pct, 1),
            gaps=gaps,
            effort_estimate_hours=self._effort(deal, requirements),
            winrate_estimate=round(winrate, 1),
            verdict=verdict,
            driving_factors=drivers + factors.notes,
        )

    def sensitivity(
        self,
        cases: list[tuple[DealContext, str]],
        trials: int = 500,
        jitter: float = 0.25,
        seed: int = 20260721,
    ) -> dict[str, float]:
        """How often the verdicts survive random perturbation of the weights.

        Six labelled scenarios cannot validate six parameters. This reports whether the
        model sits on a plateau or on a knife edge, which is the honest thing to publish
        alongside an accuracy figure.
        """
        rng = random.Random(seed)
        all_correct = 0
        per_case = {sid: 0 for _, sid in [(c, c[0].scenario_id) for c in cases]}
        for _ in range(trials):
            perturbed = {
                k: max(0.01, v * (1 + rng.uniform(-jitter, jitter)))
                for k, v in WEIGHTS.items()
            }
            total = sum(perturbed.values())
            perturbed = {k: v / total for k, v in perturbed.items()}
            qualifier = BidQualifier(perturbed)
            correct = 0
            for deal, expected in cases:
                if qualifier.assess(deal).verdict.value == expected:
                    correct += 1
                    per_case[deal.scenario_id] += 1
            if correct == len(cases):
                all_correct += 1
        return {
            "trials": float(trials),
            "jitter": jitter,
            "all_correct_rate": all_correct / trials,
            **{f"stable_{sid}": n / trials for sid, n in per_case.items()},
        }

    # --- internals ------------------------------------------------------------------

    def _factors(self, deal: DealContext, fit_pct: float) -> _Factors:
        notes: list[str] = []

        # A deep relationship alongside a strong incumbent almost always means the
        # incumbent is us. Reading it as a threat would invert the situation.
        we_are_incumbent = (
            deal.relationship_depth == "DEEP" and deal.incumbent_strength != "NONE"
        )
        if we_are_incumbent:
            incumbency = 1.0
            notes.append("deep relationship implies we hold the incumbency")
        else:
            incumbency = INCUMBENT.get(deal.incumbent_strength, 0.45)

        # Each competitor beyond a normal shortlist of two erodes the position.
        competition = max(0.1, 1.0 - max(0, deal.competitor_count - 2) * 0.15)

        return _Factors(
            fit=min(1.0, fit_pct / 100.0),
            relationship=RELATIONSHIP.get(deal.relationship_depth, 0.35),
            incumbency=incumbency,
            timing=TIMING.get(deal.entry_timing, 0.6),
            competition=competition,
            we_are_incumbent=we_are_incumbent,
            notes=notes,
        )

    def _winrate(self, deal: DealContext, f: _Factors) -> float:
        score = (
            self.weights["fit"] * f.fit
            + self.weights["relationship"] * f.relationship
            + self.weights["incumbency"] * f.incumbency
            + self.weights["timing"] * f.timing
            + self.weights["competition"] * f.competition
        ) / sum(self.weights.values())

        winrate = (score ** SCORE_EXPONENT) * MAX_WINRATE

        if self._late_against_incumbent(deal, f):
            winrate *= LATE_VS_INCUMBENT_MULTIPLIER
        return max(0.0, min(MAX_WINRATE, winrate))

    @staticmethod
    def _late_against_incumbent(deal: DealContext, f: _Factors) -> bool:
        return (
            deal.entry_timing == "LATE"
            and deal.incumbent_strength == "STRONG"
            and not f.we_are_incumbent
        )

    def _verdict(self, deal: DealContext, f: _Factors, winrate: float, fit_pct: float
                 ) -> tuple[BidVerdict, list[str]]:
        drivers: list[str] = []

        if self._late_against_incumbent(deal, f):
            drivers.append(
                "late entry against an entrenched incumbent: the requirement is "
                "likely already shaped"
            )
        if fit_pct < MIN_VIABLE_FIT:
            drivers.append(f"mandatory fit {fit_pct:.0f}% is below the viable floor")
            return BidVerdict.NO_BID, drivers
        if winrate < NO_BID_WINRATE:
            drivers.append(f"win probability {winrate:.0f}% is below the 20% floor")
            return BidVerdict.NO_BID, drivers

        if deal.deal_size_ratio <= PRICE_PRESSURE_RATIO:
            drivers.append(
                f"deal size {deal.deal_size_ratio:.1f}x normal indicates severe price "
                "compression; partnering improves the cost position without walking away"
            )
            return BidVerdict.PARTNER_BID, drivers

        drivers.extend(self._positive_drivers(deal, f, winrate))
        return BidVerdict.BID, drivers

    @staticmethod
    def _positive_drivers(deal: DealContext, f: _Factors, winrate: float) -> list[str]:
        out = [f"win probability {winrate:.0f}%"]
        if f.fit >= 0.85:
            out.append(f"strong solution fit at {f.fit * 100:.0f}%")
        if deal.relationship_depth in {"DEEP", "MODERATE"}:
            out.append(f"{deal.relationship_depth.lower()} client relationship")
        if deal.incumbent_strength == "NONE":
            out.append("no incumbent to displace")
        if deal.entry_timing == "EARLY":
            out.append("early entry allows us to shape the requirement")
        if deal.competitor_count >= 5:
            out.append(f"crowded field of {deal.competitor_count} competitors")
        return out

    @staticmethod
    def _mandatory_fit(
        deal: DealContext,
        requirements: list[Requirement] | None,
        capabilities: set[str] | None,
    ) -> tuple[float, list[str]]:
        """Fit against MANDATORY requirements, when they are available.

        The deal context carries a stated fit percentage. When the extracted
        requirements and a capability inventory are supplied, they are authoritative,
        because a measured fit beats an asserted one.
        """
        if not requirements or capabilities is None:
            return deal.fit_percentage, []

        mandatory = [r for r in requirements if r.priority is Priority.MANDATORY]
        if not mandatory:
            return deal.fit_percentage, []

        gaps = [
            r.id for r in mandatory
            if not any(cap.lower() in r.text.lower() for cap in capabilities)
        ]
        met = len(mandatory) - len(gaps)
        return 100.0 * met / len(mandatory), gaps

    @staticmethod
    def _effort(deal: DealContext, requirements: list[Requirement] | None) -> float:
        """Indicative bid effort in hours. Scales with scope and competitive pressure."""
        base = 80.0
        if requirements:
            base += 6.0 * len([r for r in requirements if r.priority is Priority.MANDATORY])
            base += 3.0 * len([r for r in requirements if r.priority is not Priority.MANDATORY])
        base *= 1.0 + 0.08 * max(0, deal.competitor_count - 2)
        base *= max(0.6, min(1.8, deal.deal_size_ratio))
        return round(base, 1)
