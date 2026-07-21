"""W1 Task Router — Phase 10. DETERMINISTIC: zero LLM calls.

Creates human tasks for STAKEHOLDER and GAP items, routed by owning department.

A task is the system's way of saying "a human must do this", so it must be impossible to
lose. Every escalated section and every GAP requirement produces one, with an owner and
a due date derived from the submission deadline rather than from a default, because a
task due after the deadline is not a task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.models.schemas import (
    Fit,
    GeneratedSection,
    Priority,
    ProofMatch,
    Requirement,
    SectionStatus,
)

#: Subject matter -> owning department. First match wins, so order is by specificity.
DEPARTMENT_ROUTES: list[tuple[str, str]] = [
    (r"legal|liabilit|indemnit|warrant|contract|terms and conditions", "Legal"),
    (r"complian\w+|regulat\w+|rbi|gdpr|dpdp|statutory|audit", "Compliance"),
    (r"secur\w+|penetration|encryption|rbac|access control", "Information Security"),
    (r"cost|pricing|commercial|discount|margin|payment", "Commercial"),
    (r"resourc\w+|staff|team|fte|hiring", "Resourcing"),
    (r"architect\w+|integration|platform|technical|api", "Solution Architecture"),
    (r"reference|case study|client|testimonial", "Client Development"),
]
DEFAULT_DEPARTMENT = "Bid Management"

#: Lead time before submission, by priority. A mandatory gap needs more runway.
LEAD_DAYS = {Priority.MANDATORY: 7, Priority.WEIGHTED: 4, Priority.NICE_TO_HAVE: 2}


@dataclass
class HumanTask:
    """Work that cannot be automated. Never silently absorbed."""

    id: str
    title: str
    detail: str
    department: str
    priority: Priority
    due_date: date | None = None
    section_id: str | None = None
    requirement_ids: list[str] = field(default_factory=list)
    status: str = "OPEN"
    source: str = "GAP"

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"


class TaskRouter:
    """Creates and routes human tasks. One public method: route()."""

    def route(
        self,
        sections: list[GeneratedSection],
        requirements: list[Requirement],
        proof_matches: list[ProofMatch],
        submission_deadline: date | None = None,
    ) -> list[HumanTask]:
        by_id = {r.id: r for r in requirements}
        tasks: list[HumanTask] = []
        covered_requirements: set[str] = set()

        for section in sections:
            if section.status is not SectionStatus.ESCALATED:
                continue
            section_reqs = self._requirements_named_in(section, by_id)
            covered_requirements.update(r.id for r in section_reqs)
            priority = self._highest_priority(section_reqs)
            tasks.append(HumanTask(
                id=f"T-{len(tasks) + 1:03d}",
                title=f"Author section: {section.title}",
                detail=(
                    f"Section {section.section_id} was escalated and needs human "
                    f"authorship. It covers "
                    f"{len(section_reqs)} requirement(s)."
                ),
                department=self._department(f"{section.title} {section.content_md[:400]}"),
                priority=priority,
                due_date=self._due(submission_deadline, priority),
                section_id=section.section_id,
                requirement_ids=[r.id for r in section_reqs],
                source="ESCALATED_SECTION",
            ))

        # A GAP not already covered by an escalated section still needs an owner.
        for match in proof_matches:
            if match.fit is not Fit.GAP or match.requirement_id in covered_requirements:
                continue
            requirement = by_id.get(match.requirement_id)
            if requirement is None:
                continue
            tasks.append(HumanTask(
                id=f"T-{len(tasks) + 1:03d}",
                title=f"Evidence gap: {match.requirement_id}",
                detail=(
                    f"{requirement.text}\n\nNo proof point supports this requirement. "
                    f"Supply evidence, propose a partner, or advise that we decline it."
                ),
                department=self._department(requirement.text),
                priority=requirement.priority,
                due_date=self._due(submission_deadline, requirement.priority),
                requirement_ids=[requirement.id],
                source="GAP",
            ))
        return tasks

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _requirements_named_in(section: GeneratedSection,
                               by_id: dict[str, Requirement]) -> list[Requirement]:
        """Requirement ids the escalated brief itself lists."""
        found = re.findall(r"\b(R-\d{3,4})\b", section.content_md)
        return [by_id[rid] for rid in dict.fromkeys(found) if rid in by_id]

    @staticmethod
    def _highest_priority(requirements: list[Requirement]) -> Priority:
        if any(r.priority is Priority.MANDATORY for r in requirements):
            return Priority.MANDATORY
        if any(r.priority is Priority.WEIGHTED for r in requirements):
            return Priority.WEIGHTED
        return Priority.NICE_TO_HAVE if requirements else Priority.WEIGHTED

    @staticmethod
    def _department(text: str) -> str:
        for pattern, department in DEPARTMENT_ROUTES:
            if re.search(pattern, text, re.I):
                return department
        return DEFAULT_DEPARTMENT

    @staticmethod
    def _due(deadline: date | None, priority: Priority) -> date | None:
        """Work back from the submission deadline. A task due after it is not a task."""
        if deadline is None:
            return None
        due = deadline - timedelta(days=LEAD_DAYS[priority])
        return max(due, date.today())
