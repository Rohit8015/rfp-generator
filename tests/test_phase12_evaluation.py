"""Phase 12 acceptance test — evaluation harness and packaging.

Gate: pytest green, the evaluation suite runs, and a fresh clone can follow the README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_evaluation_module_imports() -> None:
    from src.evaluate import Evaluator, render

    assert callable(render)
    assert hasattr(Evaluator, "run")


def test_report_renders_with_targets_and_caveats() -> None:
    from src.evaluate import Evaluation, render

    ev = Evaluation()
    ev.add("A metric", "99%", ">= 90%", True)
    ev.add("A missed metric", "10%", ">= 90%", False)
    ev.add("An untargeted metric", "42", note="context")
    ev.caveats.append("something that qualifies the above")

    report = render(ev)
    assert "PASS" in report and "MISS" in report
    assert "1 target(s) met, 1 missed" in report
    assert "something that qualifies the above" in report
    assert "## Caveats" in report


def test_sealed_set_is_not_read_by_default() -> None:
    """The held-out set is spent once, by a human who decided to spend it.

    Naming the files in a docstring is fine; building a path to them is not.
    """
    source = (ROOT / "src" / "evaluate.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert '"sealed"' not in code and "'sealed'" not in code, (
        "evaluate.py builds a path into the sealed directory"
    )
    assert "--sealed" in source, "there must be an explicit opt-in to open the seal"


def test_sealed_files_are_never_opened_during_an_offline_evaluation(tmp_path,
                                                                    monkeypatch) -> None:
    """Belt and braces: watch every file open during a run and assert none is sealed."""
    import builtins

    from config import Settings

    from src.evaluate import Evaluator

    opened: list[str] = []
    real_open = builtins.open

    def watched(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watched)
    real_read_text = Path.read_text

    def watched_read_text(self, *args, **kwargs):
        opened.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", watched_read_text)

    try:
        Evaluator(Settings(output_dir=tmp_path)).run(live=False)
    except Exception:  # noqa: BLE001 - a failed run still proves what was opened
        pass

    touched = [p for p in opened if "sealed" in p.lower() or "RFP-D" in p or "RFP-E" in p]
    assert not touched, f"the evaluation opened sealed files: {touched}"


def test_readme_documents_the_run_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in ["src.orchestrator", "src.ingestion.ingest", "src.ingestion.calibrate",
                    "streamlit run app/dashboard.py", "pip install -r requirements.txt"]:
        assert command in readme, f"README does not document `{command}`"


def test_readme_reports_the_misses_not_only_the_passes() -> None:
    """A results table containing only good numbers is marketing, not evaluation."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "caveat" in readme.lower()
    assert "0.0%" in readme, "the section-level automation rate should be stated plainly"
    assert "untestable" in readme.lower() or "not testable" in readme.lower()


def test_demo_script_exists_and_covers_failure() -> None:
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    assert "offline" in demo.lower(), "the demo script should have a wifi-failure plan"
    assert "Questions you will get" in demo


@pytest.mark.slow
def test_evaluation_suite_runs_offline(tmp_path) -> None:
    """The harness itself must work without a provider, even if its E2E figures do not."""
    from config import Settings

    from src.evaluate import Evaluator, render

    evaluation = Evaluator(Settings(output_dir=tmp_path)).run(live=False)
    assert evaluation.metrics
    assert evaluation.caveats
    assert "not read" in " ".join(evaluation.caveats).lower()

    report = render(evaluation)
    assert "# Evaluation report" in report
    assert "Requirement recall" in report
