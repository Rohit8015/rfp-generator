"""W2 Task Tracker — Phase 10. DETERMINISTIC: zero LLM calls.

Status, due dates, reminder simulation and overdue marking.
notify() is a deliberate stub with a clean extension point. Never sends email.

CLAUDE.md: never auto-send email, never auto-submit a response. notify() records what
WOULD be sent and returns it. Wiring it to a real transport is a deliberate act someone
has to take, not something that happens because a dependency appeared.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from src.models.schemas import Priority
from src.workflow.router import HumanTask

log = logging.getLogger(__name__)

OPEN = "OPEN"
IN_PROGRESS = "IN_PROGRESS"
DONE = "DONE"
OVERDUE = "OVERDUE"

VALID_STATUSES = {OPEN, IN_PROGRESS, DONE, OVERDUE}


@dataclass
class Notification:
    """A message that would have been sent. Recorded, never delivered."""

    task_id: str
    department: str
    subject: str
    body: str
    would_send_at: date


@dataclass
class TaskTracker:
    """Tracks human tasks. One public method: update()."""

    tasks: list[HumanTask] = field(default_factory=list)
    sent: list[Notification] = field(default_factory=list)

    # --- public ---------------------------------------------------------------------

    def update(self, today: date | None = None) -> dict[str, object]:
        """Mark overdue tasks, queue reminders, and summarise the position."""
        today = today or date.today()
        for task in self.tasks:
            if task.status in (DONE, IN_PROGRESS):
                continue
            if task.due_date and task.due_date < today:
                task.status = OVERDUE

        for task in self.tasks:
            if task.status in (OPEN, OVERDUE) and self._needs_reminder(task, today):
                self.sent.append(self._notify(task, today))

        return self.summary(today)

    def summary(self, today: date | None = None) -> dict[str, object]:
        today = today or date.today()
        counts: dict[str, int] = {}
        for task in self.tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        blocking = [
            t.id for t in self.tasks
            if t.priority is Priority.MANDATORY and t.status != DONE
        ]
        return {
            "total": len(self.tasks),
            "by_status": counts,
            "open": sum(1 for t in self.tasks if t.is_open),
            "overdue": sum(1 for t in self.tasks if t.status == OVERDUE),
            "blocking_mandatory": blocking,
            "notifications_queued": len(self.sent),
            "as_at": today.isoformat(),
        }

    def set_status(self, task_id: str, status: str) -> HumanTask:
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {VALID_STATUSES}")
        for task in self.tasks:
            if task.id == task_id:
                task.status = status
                return task
        raise KeyError(f"no task {task_id}")

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _needs_reminder(task: HumanTask, today: date) -> bool:
        if task.due_date is None:
            return False
        days_left = (task.due_date - today).days
        return days_left <= 2  # includes overdue

    def _notify(self, task: HumanTask, today: date) -> Notification:
        """Extension point. Records the message; never sends it.

        To wire this to a real transport, replace the body of this method. Nothing else
        in the system needs to change, and nothing else in the system sends anything.
        """
        state = "OVERDUE" if task.status == OVERDUE else "due shortly"
        note = Notification(
            task_id=task.id,
            department=task.department,
            subject=f"[{task.priority.value}] {task.title} — {state}",
            body=(
                f"{task.detail}\n\n"
                f"Owner: {task.department}\n"
                f"Due: {task.due_date}\n"
                f"Requirements: {', '.join(task.requirement_ids) or 'n/a'}"
            ),
            would_send_at=today,
        )
        log.info("notification queued (not sent) for %s -> %s", task.id, task.department)
        return note

    # --- reporting ------------------------------------------------------------------

    def render(self) -> str:
        """The task list as it appears in the delivered package."""
        if not self.tasks:
            return "## Human tasks\n\nNo human tasks were raised.\n"
        lines = [
            "## Human tasks",
            "",
            f"{len(self.tasks)} task(s) require human input before submission.",
            "",
            "| Task | Owner | Priority | Due | Status | Covers |",
            "|---|---|---|---|---|---|",
        ]
        for task in self.tasks:
            lines.append(
                f"| {task.id} {task.title} | {task.department} | {task.priority.value} "
                f"| {task.due_date or '—'} | {task.status} "
                f"| {', '.join(task.requirement_ids) or '—'} |"
            )
        return "\n".join(lines) + "\n"
