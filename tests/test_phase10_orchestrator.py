"""Phase 10 acceptance test — orchestrator, workflow and the regeneration loop.

Gate: one command turns a seed RFP into a full package.

The end-to-end test runs offline and is marked `slow`. It exercises every join in the
pipeline without spending model calls; a live run is a separate, manual check.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.models.schemas import (
    DeliverableForm,
    Fit,
    GeneratedSection,
    Priority,
    ProofMatch,
    ProvenanceKind,
    ProvenanceRecord,
    ReqType,
    Requirement,
    SectionStatus,
)
from src.workflow.router import DEFAULT_DEPARTMENT, TaskRouter
from src.workflow.tracker import DONE, OVERDUE, TaskTracker

ROOT = Path(__file__).parent.parent
RFP_A = ROOT / "data" / "incoming" / "RFP-A_questionnaire_nbfc.md"


def _requirement(rid: str, text: str, priority=Priority.MANDATORY) -> Requirement:
    return Requirement(id=rid, source_section="2.1", text=text,
                       req_type=ReqType.SHALL_REQUIREMENT, priority=priority,
                       deliverable_form=DeliverableForm.PROSE)


def _escalated(section_id: str, title: str, body: str) -> GeneratedSection:
    content = f"## {title}\n\n{body}\n"
    return GeneratedSection(
        section_id=section_id, title=title, deliverable_form=DeliverableForm.PROSE,
        content_md=content, status=SectionStatus.ESCALATED,
        sentences=[ProvenanceRecord(section_id=section_id, sentence_index=0,
                                    sentence=body, kind=ProvenanceKind.STAKEHOLDER)],
    )


# --------------------------------------------------------------------------------------
# W1 Task Router
# --------------------------------------------------------------------------------------


def test_every_gap_gets_an_owned_task() -> None:
    reqs = [_requirement("R-001", "The vendor shall provide multi-lingual support."),
            _requirement("R-002", "The vendor shall implement fraud detection.")]
    matches = [ProofMatch(requirement_id="R-001", fit=Fit.GAP),
               ProofMatch(requirement_id="R-002", fit=Fit.STRONG, proof_ids=["PP-001"])]

    tasks = TaskRouter().route([], reqs, matches)
    assert len(tasks) == 1
    assert tasks[0].requirement_ids == ["R-001"]
    assert tasks[0].department
    assert tasks[0].is_open


def test_escalated_section_gets_a_task() -> None:
    reqs = [_requirement("R-001", "The vendor shall accept unlimited liability.")]
    section = _escalated("S-01", "Legal", "Requires human authorship. Covers R-001.")
    tasks = TaskRouter().route([section], reqs, [])
    assert len(tasks) == 1
    assert tasks[0].section_id == "S-01"
    assert tasks[0].department == "Legal"


def test_tasks_route_to_the_owning_department() -> None:
    cases = {
        "The vendor shall accept unlimited liability.": "Legal",
        "The vendor shall comply with RBI guidelines.": "Compliance",
        "The vendor shall conduct penetration testing.": "Information Security",
        "Submit a detailed pricing schedule.": "Commercial",
        "Provide three client references.": "Client Development",
        "Supply trained alpacas to reception.": DEFAULT_DEPARTMENT,
    }
    for text, expected in cases.items():
        reqs = [_requirement("R-001", text)]
        tasks = TaskRouter().route([], reqs, [ProofMatch(requirement_id="R-001",
                                                         fit=Fit.GAP)])
        assert tasks[0].department == expected, f"{text!r} routed to {tasks[0].department}"


def test_due_dates_work_back_from_the_deadline() -> None:
    deadline = date.today() + timedelta(days=30)
    reqs = [_requirement("R-001", "A mandatory thing.", Priority.MANDATORY),
            _requirement("R-002", "A nice-to-have thing.", Priority.NICE_TO_HAVE)]
    matches = [ProofMatch(requirement_id=r.id, fit=Fit.GAP) for r in reqs]
    tasks = {t.requirement_ids[0]: t for t in TaskRouter().route([], reqs, matches,
                                                                 deadline)}
    assert tasks["R-001"].due_date < tasks["R-002"].due_date, "mandatory needs more runway"
    assert all(t.due_date <= deadline for t in tasks.values()), "a task due after the "
    "deadline is not a task"


def test_a_gap_covered_by_an_escalated_section_is_not_duplicated() -> None:
    reqs = [_requirement("R-001", "The vendor shall do a thing.")]
    section = _escalated("S-01", "Thing", "Not drafted. Covers R-001.")
    matches = [ProofMatch(requirement_id="R-001", fit=Fit.GAP)]
    assert len(TaskRouter().route([section], reqs, matches)) == 1


# --------------------------------------------------------------------------------------
# W2 Tracker
# --------------------------------------------------------------------------------------


def test_overdue_tasks_are_marked_and_reminded() -> None:
    reqs = [_requirement("R-001", "A thing.")]
    tasks = TaskRouter().route([], reqs, [ProofMatch(requirement_id="R-001", fit=Fit.GAP)],
                               date.today() + timedelta(days=1))
    tasks[0].due_date = date.today() - timedelta(days=3)

    tracker = TaskTracker(tasks=tasks)
    summary = tracker.update()
    assert tasks[0].status == OVERDUE
    assert summary["overdue"] == 1
    assert tracker.sent, "an overdue task should queue a reminder"


def test_notifications_are_recorded_never_sent() -> None:
    """CLAUDE.md: never auto-send email. notify() records what WOULD be sent."""
    source = (ROOT / "src" / "workflow" / "tracker.py").read_text(encoding="utf-8").lower()
    for forbidden in ["smtplib", "sendmail", "requests.post", "httpx.post", "send_message"]:
        assert forbidden not in source, f"tracker.py references {forbidden}"


def test_completed_tasks_stop_blocking() -> None:
    reqs = [_requirement("R-001", "A mandatory thing.")]
    tracker = TaskTracker(tasks=TaskRouter().route(
        [], reqs, [ProofMatch(requirement_id="R-001", fit=Fit.GAP)]))
    assert tracker.summary()["blocking_mandatory"]
    tracker.set_status(tracker.tasks[0].id, DONE)
    assert not tracker.summary()["blocking_mandatory"]


def test_unknown_status_is_rejected() -> None:
    tracker = TaskTracker(tasks=[])
    with pytest.raises(ValueError, match="unknown status"):
        tracker.set_status("T-001", "MAYBE")


# --------------------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------------------


@pytest.mark.slow
def test_one_command_produces_the_full_package(tmp_path) -> None:
    """The phase gate: an RFP in, a complete package out."""
    from config import Settings

    from src.orchestrator import Orchestrator

    settings = Settings(output_dir=tmp_path, llm_cache_enabled=False)
    result = Orchestrator(settings=settings, use_llm=False).run(RFP_A)

    assert result.requirements, "no requirements extracted"
    assert result.buyer is not None
    assert result.outline is not None and result.outline.sections
    assert result.sections, "no sections generated"

    package = result.package
    assert package is not None
    assert package.markdown_path.is_file()
    assert package.report_path.is_file()
    assert package.docx_path is not None and package.docx_path.is_file()

    document = package.markdown_path.read_text(encoding="utf-8")
    assert "Requirements compliance matrix" in document
    assert "Human tasks" in document

    report = package.report_path.read_text(encoding="utf-8")
    assert "Automation rate" in report
    assert "Where the text came from" in report


@pytest.mark.slow
def test_every_requirement_is_traced_end_to_end(tmp_path) -> None:
    """No requirement may be silently dropped between extraction and the matrix."""
    from config import Settings

    from src.orchestrator import Orchestrator

    result = Orchestrator(settings=Settings(output_dir=tmp_path), use_llm=False).run(RFP_A)
    extracted = {r.id for r in result.requirements}
    in_outline = result.outline.covered_requirement_ids()
    in_matrix = {row.requirement_id for row in result.matrix.rows}

    assert in_outline == extracted, f"lost between extraction and outline: " \
                                    f"{extracted - in_outline}"
    assert in_matrix == extracted, f"lost between outline and matrix: " \
                                   f"{extracted - in_matrix}"


@pytest.mark.slow
def test_run_record_is_persisted(tmp_path) -> None:
    from config import Settings

    from src.models import db
    from src.orchestrator import Orchestrator

    settings = Settings(output_dir=tmp_path, db_dir=tmp_path)
    result = Orchestrator(settings=settings, use_llm=False).run(RFP_A)

    conn = db.connect(settings.sqlite_path)
    stored = db.load_run(conn, result.run.id)
    conn.close()
    assert stored is not None
    assert stored.status == "COMPLETE"
    assert stored.sections_total == len(result.sections)
    assert stored.timings, "per-agent timings were not recorded"


@pytest.mark.slow
def test_a_failing_section_escalates_rather_than_killing_the_run(tmp_path,
                                                                monkeypatch) -> None:
    """A run that dies halfway is worth nothing; one that escalates is a draft plus tasks."""
    from config import Settings

    from src.agents import generator as gen
    from src.orchestrator import Orchestrator

    original = gen.GenerationRouter.generate
    calls = {"n": 0}

    def explode(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated writer failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(gen.GenerationRouter, "generate", explode)
    result = Orchestrator(settings=Settings(output_dir=tmp_path), use_llm=False).run(RFP_A)

    assert result.package is not None, "the run did not complete"
    assert any(s.status is SectionStatus.ESCALATED for s in result.sections)
