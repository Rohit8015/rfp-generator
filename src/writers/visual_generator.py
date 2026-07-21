"""Visual generator — Phase 8. DETERMINISTIC: zero LLM calls.

Handles GANTT and CHART. Renders matplotlib Gantt, phased investment profile with a
cumulative line, risk heat map and capability map to PNG.

Charts are drawn from the cost model's own numbers, never from separately supplied
figures. A chart that disagrees with the table beside it is the classic proposal error,
and it happens whenever the two are built from different sources. Here the Gantt reads
the same phase list the cost table totals, so they cannot diverge.

Matplotlib runs on the Agg backend: chart rendering must work headless, in a test run
and on a demo machine with no display.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: set before pyplot is imported anywhere

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from src.models.schemas import (  # noqa: E402
    GeneratedSection,
    OutlineSection,
    ProvenanceKind,
    SectionStatus,
)
from src.utils import provenance  # noqa: E402
from src.writers.quant_modeler import CostModel  # noqa: E402

DPI = 144
FIGSIZE_WIDE = (11, 5.5)

#: Colour-blind safe, print-legible. Consistent across every chart in the pack.
PALETTE = ["#2b6cb0", "#38a169", "#d69e2e", "#805ad5", "#dd6b20", "#319795", "#e53e3e"]
RISK_COLOURS = ["#38a169", "#d69e2e", "#dd6b20", "#e53e3e"]


class VisualGenerator:
    """Renders the chart pack. One public method: write()."""

    def __init__(self, settings=None) -> None:
        if settings is None:
            from config import get_settings

            settings = get_settings()
        self.settings = settings
        self.output_dir = Path(settings.output_path) / "charts"

    # --- public ---------------------------------------------------------------------

    def write(
        self,
        section: OutlineSection,
        model: CostModel | None = None,
        risks: list[dict] | None = None,
        capabilities: list[dict] | None = None,
    ) -> GeneratedSection:
        """Render whichever charts the supplied data supports."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        assets: list[str] = []
        described: list[str] = []

        if model is not None:
            assets.append(str(self.gantt(model)))
            described.append(
                f"The delivery schedule spans {model.total_weeks} weeks across "
                f"{len(model.phases)} phases, shown in the Gantt chart."
            )
            assets.append(str(self.investment_profile(model)))
            described.append(
                "The phased investment profile shows spend by phase with cumulative "
                "commitment against the total."
            )
        if risks:
            assets.append(str(self.risk_heat_map(risks)))
            described.append(
                f"The risk heat map plots {len(risks)} identified risks by likelihood "
                "and impact."
            )
        if capabilities:
            assets.append(str(self.capability_map(capabilities)))
            described.append(
                f"The capability map compares current and target maturity across "
                f"{len(capabilities)} capabilities."
            )

        content = f"## {section.title}\n\n" + "\n\n".join(described) + "\n"
        if not described:
            content = (
                f"## {section.title}\n\nNo chart data was supplied for this section.\n"
            )

        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, ProvenanceKind.COMPUTED
            ),
            asset_paths=assets,
            status=SectionStatus.DRAFTED if assets else SectionStatus.ESCALATED,
        )

    # --- charts ---------------------------------------------------------------------

    def gantt(self, model: CostModel, filename: str = "gantt.png") -> Path:
        """Phase schedule. Reads the same phase list the cost table totals."""
        fig, ax = plt.subplots(figsize=FIGSIZE_WIDE)
        names = [p.name for p in model.phases][::-1]
        for index, phase in enumerate(reversed(model.phases)):
            ax.barh(index, phase.weeks, left=phase.start_week, height=0.55,
                    color=PALETTE[index % len(PALETTE)], edgecolor="white")
            ax.text(phase.start_week + phase.weeks / 2, index,
                    f"{phase.weeks}w · {phase.fte} FTE",
                    ha="center", va="center", color="white", fontsize=8, weight="bold")

        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=9)
        ax.set_xlabel("Programme week")
        ax.set_title(f"Delivery schedule — {model.total_weeks} weeks", loc="left",
                     fontsize=12, weight="bold")
        ax.set_xlim(0, model.total_weeks)
        ax.grid(axis="x", alpha=0.25, linestyle=":")
        ax.spines[["top", "right"]].set_visible(False)
        return self._save(fig, filename)

    def investment_profile(self, model: CostModel, filename: str = "investment.png"
                           ) -> Path:
        """Spend by phase with a cumulative line, on a second axis."""
        fig, ax = plt.subplots(figsize=FIGSIZE_WIDE)
        names = [p.name for p in model.phases]
        costs = [p.services_cost for p in model.phases]
        cumulative: list[float] = []
        running = 0.0
        for cost in costs:
            running += cost
            cumulative.append(running)

        symbol = "₹" if model.currency == "INR" else "€"
        scale, unit = (1e7, "Cr") if model.currency == "INR" else (1e6, "M")

        ax.bar(names, [c / scale for c in costs], color=PALETTE[0], alpha=0.85,
               label="Phase services cost")
        ax.set_ylabel(f"Phase cost ({symbol}{unit})")
        ax.set_title("Phased investment profile", loc="left", fontsize=12, weight="bold")
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        for label in ax.get_xticklabels():
            label.set_ha("right")

        right = ax.twinx()
        right.plot([c / scale for c in cumulative], color=PALETTE[4], marker="o",
                   linewidth=2, label="Cumulative")
        right.set_ylabel(f"Cumulative ({symbol}{unit})")
        right.set_ylim(0, max(cumulative) / scale * 1.15)

        ax.spines[["top"]].set_visible(False)
        right.spines[["top"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25, linestyle=":")
        fig.legend(loc="upper left", bbox_to_anchor=(0.12, 0.88), frameon=False,
                   fontsize=9)
        return self._save(fig, filename)

    def risk_heat_map(self, risks: list[dict], filename: str = "risk_heatmap.png") -> Path:
        """Likelihood against impact, 1-5 each, with risks placed on the grid."""
        fig, ax = plt.subplots(figsize=(7.5, 6))
        for x in range(5):
            for y in range(5):
                severity = (x + 1) * (y + 1)
                band = 0 if severity <= 4 else 1 if severity <= 9 else 2 if severity <= 15 else 3
                ax.add_patch(Rectangle((x + 0.5, y + 0.5), 1, 1,
                                       facecolor=RISK_COLOURS[band], alpha=0.25,
                                       edgecolor="white"))
        for index, risk in enumerate(risks, start=1):
            likelihood = self._level(risk.get("likelihood", 3))
            impact = self._level(risk.get("impact", 3))
            ax.scatter(likelihood, impact, s=320, color=PALETTE[0], zorder=3,
                       edgecolor="white", linewidth=1.5)
            ax.text(likelihood, impact, str(index), color="white", ha="center",
                    va="center", fontsize=9, weight="bold", zorder=4)

        ax.set_xlim(0.5, 5.5)
        ax.set_ylim(0.5, 5.5)
        ax.set_xticks(range(1, 6))
        ax.set_yticks(range(1, 6))
        ax.set_xlabel("Likelihood")
        ax.set_ylabel("Impact")
        ax.set_title("Risk heat map", loc="left", fontsize=12, weight="bold")
        ax.set_aspect("equal")
        return self._save(fig, filename)

    def capability_map(self, capabilities: list[dict], filename: str = "capability.png"
                       ) -> Path:
        """Current against target maturity, one horizontal band per capability."""
        fig, ax = plt.subplots(figsize=(10, max(4, 0.5 * len(capabilities) + 2)))
        names = [c.get("name", f"Capability {i}") for i, c in enumerate(capabilities, 1)]
        current = [float(c.get("current", 1)) for c in capabilities]
        target = [float(c.get("target", 5)) for c in capabilities]
        positions = range(len(names))

        for pos, cur, tgt in zip(positions, current, target):
            ax.plot([cur, tgt], [pos, pos], color="#cbd5e0", linewidth=6,
                    solid_capstyle="round", zorder=1)
        ax.scatter(current, list(positions), s=110, color=PALETTE[0], zorder=3,
                   label="Current")
        ax.scatter(target, list(positions), s=110, color=PALETTE[1], zorder=3,
                   label="Target")

        ax.set_yticks(list(positions))
        ax.set_yticklabels(names, fontsize=9)
        ax.set_xlim(0, 5.5)
        ax.set_xlabel("Maturity (1 = initial, 5 = optimised)")
        ax.set_title("Capability maturity: current against target", loc="left",
                     fontsize=12, weight="bold")
        ax.grid(axis="x", alpha=0.25, linestyle=":")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=9, loc="lower right")
        return self._save(fig, filename)

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _level(value) -> int:
        """Accept 1-5, or the words used in a RAID register."""
        words = {"very low": 1, "low": 2, "medium": 3, "moderate": 3, "high": 4,
                 "very high": 5, "critical": 5}
        if isinstance(value, str):
            return words.get(value.strip().lower(), 3)
        return max(1, min(5, int(value)))

    def _save(self, fig, filename: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / filename
        fig.tight_layout()
        fig.savefig(path, dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        return path
