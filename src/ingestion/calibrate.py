"""Retrieval threshold calibration — Phase 2.

Contract: derives the REUSE / ADAPT / SYNTHESIZE boundaries from the actual similarity
distribution of this corpus under this embedding model, and writes them to
config/thresholds.json plus a human-readable calibration_report.md.

Why this exists: v1 hardcoded 0.85 / 0.70. Those numbers are meaningless across a change
of embedding model or corpus. `ContextPack` refuses to carry a reuse_decision without a
calibration_version, so nothing downstream can quietly fall back to a guess.

Method: unsupervised percentile calibration on the corpus's own similarity distribution.
All pairs of historical questions are scored against each other, and the thresholds are
placed at high percentiles of that distribution. A REUSE match must be more similar than
essentially every unrelated pair in the corpus.

Why not the supplied labels. calibration_pairs.json ships a `relation` label and a
`similarity_score` per pair, and an earlier version of this module calibrated on them.
Measurement showed the labels do not survive contact with any embedding of the text:

    NEAR_IDENTICAL median 0.829 | ADAPT median 0.781 | SYNTHESIZE median 0.826

SYNTHESIZE outranks ADAPT, and the same inversion appears in retrieval_pairs.json
(ADAPT 0.837 vs SYNTHESIZE 0.855). Inspection explains it: pairs such as "How do you
ensure GDPR compliance?" against "How do you ensure GDPR compliance for European
clients?" are labelled SYNTHESIZE, when they are near-duplicates. Five of the six
SYNTHESIZE pairs are mislabelled this way. Thresholds derived from them would be
arbitrary, so the labels are reported as a diagnostic and set nothing.

Two further things this deliberately does NOT do:

1. It does not trust the shipped `similarity_score`. Those are part of the label, not a
   measurement from this embedder. Calibrating on them would be circular.

2. It does not calibrate STAKEHOLDER. That decision comes from the Compliance/Legal/GAP
   guardrail, not from a similarity score, and must never be reachable by a high match.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import date

from config import get_settings
from src.models.schemas import CalibrationThresholds

log = logging.getLogger(__name__)

#: Label -> the decision that label implies.
RELATION_TO_DECISION = {
    "NEAR_IDENTICAL": "REUSE",
    "ADAPT": "ADAPT",
    "SYNTHESIZE": "SYNTHESIZE",
}


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # embeddings are L2-normalised at source


def _pct(values: list[float], p: float) -> float:
    """Percentile by linear interpolation. Small n, so avoid numpy's edge conventions."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Calibrator:
    """Derives thresholds from labelled pairs. One public method: run()."""

    def __init__(self, settings=None, provider=None) -> None:
        self.settings = settings or get_settings()
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider

    #: A REUSE candidate must beat this share of all unrelated corpus pairs.
    REUSE_PERCENTILE = 99.5
    #: An ADAPT candidate must beat this share.
    ADAPT_PERCENTILE = 97.0

    def run(self) -> CalibrationThresholds:
        background = self._background_distribution()
        thresholds = self._derive(background)
        diagnostic = self._label_diagnostic(thresholds)
        self._write_thresholds(thresholds)
        self._write_report(thresholds, diagnostic)
        return thresholds

    def _background_distribution(self) -> list[float]:
        """All-pairs similarity between historical questions.

        This is the distribution of "two questions that happen to sit in the same
        corpus". A genuine near-duplicate must stand far above it.
        """
        questions = self._historical_questions()
        vecs = self.provider.embed(list(questions.values()))
        sims: list[float] = []
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                sims.append(_cosine(vecs[i], vecs[j]))
        log.info("background distribution: %d pairs from %d questions",
                 len(sims), len(vecs))
        return sims

    def _derive(self, background: list[float]) -> CalibrationThresholds:
        """Place thresholds at high percentiles of the background distribution."""
        if len(background) < 100:
            raise ValueError(
                f"background distribution has only {len(background)} pairs; "
                "too few to place a percentile threshold"
            )
        reuse_min = _pct(background, self.REUSE_PERCENTILE)
        adapt_min = _pct(background, self.ADAPT_PERCENTILE)

        return CalibrationThresholds(
            version=f"{date.today().isoformat()}-{self.settings.embedding_model.split('/')[-1]}",
            method=(
                f"unsupervised percentile calibration on corpus self-similarity; "
                f"REUSE at p{self.REUSE_PERCENTILE}, ADAPT at p{self.ADAPT_PERCENTILE}"
            ),
            embedding_model=self.settings.embedding_model,
            reuse_min=round(reuse_min, 4),
            adapt_min=round(adapt_min, 4),
            n_pairs=len(background),
            observed={
                "background": {
                    "n": float(len(background)),
                    "min": round(min(background), 4),
                    "median": round(statistics.median(background), 4),
                    "p90": round(_pct(background, 90), 4),
                    "p97": round(_pct(background, 97), 4),
                    "p99_5": round(_pct(background, 99.5), 4),
                    "max": round(max(background), 4),
                }
            },
            separation=round(reuse_min - statistics.median(background), 4),
        )

    # --- internals ------------------------------------------------------------------

    def _load_pairs(self) -> list[dict]:
        path = self.settings.data_path / "eval" / "calibration_pairs.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        pairs = obj["calibration_pairs"] if isinstance(obj, dict) else obj
        unknown = {p["relation"] for p in pairs} - set(RELATION_TO_DECISION)
        if unknown:
            raise ValueError(f"unknown relation labels in calibration set: {unknown}")
        return pairs

    def _historical_questions(self) -> dict[str, str]:
        """HQ id -> question text, across every historical_rfps file."""
        out: dict[str, str] = {}
        for path in sorted((self.settings.data_path / "historical_rfps").glob("*.json")):
            obj = json.loads(path.read_text(encoding="utf-8"))
            records = (next(v for v in obj.values() if isinstance(v, list))
                       if isinstance(obj, dict) else obj)
            for r in records:
                out[r["id"]] = r["question"]
        if not out:
            raise ValueError("no historical questions found; run ingestion first")
        return out

    def _label_diagnostic(self, t: CalibrationThresholds) -> list[dict]:
        """Score the supplied labelled pairs against the derived thresholds.

        Purely diagnostic. It documents how far the shipped labels are from any
        measurable notion of similarity, and sets nothing.
        """
        try:
            pairs = self._load_pairs()
        except (FileNotFoundError, KeyError, ValueError) as exc:
            log.warning("label diagnostic skipped: %s", exc)
            return []
        questions = self._historical_questions()
        usable = [p for p in pairs if p["historical_id"] in questions]
        if not usable:
            return []

        q_vecs = self.provider.embed([p["question"] for p in usable])
        t_vecs = self.provider.embed([questions[p["historical_id"]] for p in usable])
        rows = []
        for pair, qv, tv in zip(usable, q_vecs, t_vecs):
            sim = _cosine(qv, tv)
            rows.append({
                "pair_id": pair["pair_id"],
                "labelled": RELATION_TO_DECISION[pair["relation"]],
                "derived": t.decide(sim).value,
                "measured": round(sim, 4),
                "label_score": pair.get("similarity_score"),
                "target": pair["historical_id"],
            })
        return rows

    def _write_thresholds(self, t: CalibrationThresholds) -> None:
        path = self.settings.thresholds_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(t.model_dump_json(indent=2) + "\n", encoding="utf-8")

    def _write_report(self, t: CalibrationThresholds, diagnostic: list[dict]) -> None:
        bg = t.observed["background"]
        lines = [
            "# Retrieval threshold calibration",
            "",
            f"- **Version:** `{t.version}`",
            f"- **Embedding model:** `{t.embedding_model}` (local, 384-dim)",
            f"- **Method:** {t.method}",
            f"- **Background pairs:** {t.n_pairs:,}",
            "",
            "## Derived thresholds",
            "",
            "| Decision | Condition |",
            "|---|---|",
            f"| REUSE | top-1 similarity >= **{t.reuse_min}** |",
            f"| ADAPT | **{t.adapt_min}** <= similarity < **{t.reuse_min}** |",
            f"| SYNTHESIZE | similarity < **{t.adapt_min}** |",
            "| STAKEHOLDER | Not score-derived. Forced by the Compliance/Legal/GAP "
            "guardrail regardless of similarity. |",
            "",
            "## Method",
            "",
            "Every pair of historical questions is scored against every other, giving the",
            "distribution of *two questions that merely share a corpus*. Thresholds sit at",
            "high percentiles of that distribution: to be called REUSE, a match must be",
            f"more similar than {self.REUSE_PERCENTILE}% of unrelated pairs.",
            "",
            "This is unsupervised. It needs no labelled relations, which matters because",
            "the labels shipped with this dataset do not hold up (see below).",
            "",
            "## Background distribution",
            "",
            "| n | min | median | p90 | p97 | p99.5 | max |",
            "|---|---|---|---|---|---|---|",
            f"| {int(bg['n']):,} | {bg['min']} | {bg['median']} | {bg['p90']} "
            f"| {bg['p97']} | {bg['p99_5']} | {bg['max']} |",
            "",
            f"The REUSE threshold sits **{t.separation:+.4f}** above the median of the",
            "background distribution.",
            "",
        ]

        if diagnostic:
            agree = sum(1 for r in diagnostic if r["labelled"] == r["derived"])
            lines += [
                "## Diagnostic: the supplied labels",
                "",
                "`calibration_pairs.json` ships a `relation` and a `similarity_score` per",
                "pair. **Neither sets any threshold here.** An earlier version of this",
                "module calibrated on them and produced incoherent bands, because the",
                "labels do not correspond to any measurable similarity:",
                "",
                "| Labelled relation | Measured median |",
                "|---|---|",
            ]
            by_label: dict[str, list[float]] = {}
            for r in diagnostic:
                by_label.setdefault(r["labelled"], []).append(r["measured"])
            for label, vals in by_label.items():
                lines.append(f"| {label} | {statistics.median(vals):.4f} |")
            lines += [
                "",
                "SYNTHESIZE scoring at or above ADAPT is the tell. Inspection confirms it:",
                'pairs such as *"How do you ensure GDPR compliance?"* against *"How do you',
                'ensure GDPR compliance for European clients?"* carry the SYNTHESIZE label',
                "while being near-duplicates. The same inversion appears independently in",
                "`retrieval_pairs.json`.",
                "",
                f"Agreement between the shipped labels and the thresholds derived here: "
                f"**{agree}/{len(diagnostic)}**. That number measures the labels, not the",
                "thresholds.",
                "",
                "**Action required:** the reuse-decision labels need re-labelling by a",
                "human before any REUSE/ADAPT/SYNTHESIZE accuracy figure can be reported.",
                "Retrieval Recall@5 and MRR are unaffected — they depend on `relevant_ids`,",
                "not on `expected_decision`.",
                "",
                "| Pair | Shipped label | Derived | Measured | Shipped score | Target |",
                "|---|---|---|---|---|---|",
            ]
            for r in sorted(diagnostic, key=lambda x: -x["measured"]):
                flag = "" if r["labelled"] == r["derived"] else " ⚠"
                lines.append(
                    f"| {r['pair_id']} | {r['labelled']}{flag} | {r['derived']} "
                    f"| {r['measured']} | {r['label_score']} | {r['target']} |"
                )

        out = self.settings.output_path
        out.mkdir(parents=True, exist_ok=True)
        (out / "calibration_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_thresholds(settings=None) -> CalibrationThresholds:
    """Read the calibrated thresholds. Raises if calibration has not been run."""
    settings = settings or get_settings()
    path = settings.thresholds_path
    if not path.is_file():
        raise FileNotFoundError(
            f"no calibration at {path}. Run `python -m src.ingestion.calibrate` first. "
            "Thresholds are never hardcoded (CLAUDE.md)."
        )
    return CalibrationThresholds.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    t = Calibrator().run()
    print(t.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
