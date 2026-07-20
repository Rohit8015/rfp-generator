"""A6 Response Architect — Phase 6.

In: requirements + BuyerProfile + themes. Out: ResponseOutline.
Two modes: compliance (mirror the buyer's structure) and narrative (consulting
proposal), chosen from BuyerProfile.submission_rules. Emits the compliance matrix
skeleton as a by-product. Every requirement lands in exactly one primary section.

DETERMINISTIC: no model call. The gate is "zero orphan requirements", and an assignment
step that can hallucinate is an assignment step that can drop a requirement. Placement
is a bookkeeping problem, so it is solved by bookkeeping: every requirement is assigned,
and anything unplaced falls into an explicit catch-all section rather than vanishing.

The outline IS the compliance matrix skeleton: `requirement_ids` per section is exactly
the traceability A11 verifies in Phase 9.
"""

from __future__ import annotations

import re

from src.models.schemas import (
    BuyerProfile,
    DeliverableForm,
    OutlineMode,
    OutlineSection,
    Priority,
    Requirement,
    ResponseOutline,
    WinTheme,
)

#: Language in the buyer's submission rules that demands their structure be mirrored.
_COMPLIANCE_SIGNALS = re.compile(
    r"prescribed (?:format|template|structure)|in the order|follow the structure|"
    r"mirror|questionnaire|respond to each|answer each|section by section|"
    r"annexure [a-z]|prescribed excel|required formats?",
    re.I,
)

#: Canonical consulting-proposal spine used in narrative mode. Order is the argument:
#: understanding before approach, approach before evidence, evidence before price.
_NARRATIVE_SPINE: list[tuple[str, str, DeliverableForm, int]] = [
    ("Executive summary", "State the recommendation and the value case up front",
     DeliverableForm.PROSE, 500),
    ("Our understanding of your situation", "Prove we understand the buyer's problem",
     DeliverableForm.PROSE, 600),
    ("Recommended approach", "The proposed solution and why it fits",
     DeliverableForm.PROSE, 900),
    ("Delivery plan and timeline", "Phasing, milestones and dependencies",
     DeliverableForm.GANTT, 500),
    ("Team and resourcing", "Who delivers this and how the team is shaped",
     DeliverableForm.TABLE, 400),
    ("Governance and assurance", "How progress is controlled and reported",
     DeliverableForm.PROSE, 450),
    ("Security, data protection and compliance", "How regulatory obligations are met",
     DeliverableForm.PROSE, 500),
    ("Evidence and references", "Comparable work and verifiable outcomes",
     DeliverableForm.TABLE, 400),
    ("Commercials", "Investment, pricing basis and assumptions",
     DeliverableForm.COSTING, 400),
    ("Assumptions, risks and exclusions", "What we assume, what could go wrong, "
     "what is out of scope", DeliverableForm.TABLE, 450),
]

#: Keywords that pull a requirement towards a narrative section.
#:
#: Matched on word boundaries, never as substrings. Short keywords make substring
#: matching actively wrong here: "ai" appears inside "det-ai-led", which routed a
#: pricing requirement to the solution section. Same failure mode as "nda" inside
#: "ma-nda-tory" in the requirement extractor.
_SECTION_KEYWORD_SOURCES: dict[str, tuple[str, ...]] = {
    "Our understanding of your situation": ("objective", "background", "current state",
                                            "challenge", "problem", "context"),
    "Recommended approach": ("platform", "system", "implement", "integrate", "solution",
                             "architecture", "migration", "ai", "ml", "analytics",
                             "dashboard", "chatbot", "mobile", "api", "automation"),
    "Delivery plan and timeline": ("timeline", "milestone", "schedule", "roadmap",
                                   "phase", "implementation plan", "deadline"),
    "Team and resourcing": ("team", "resource", "cv", "staff", "expertise", "support",
                            "24x7", "dedicated"),
    "Governance and assurance": ("governance", "sla", "penalt", "report", "review",
                                 "escalation", "monitoring", "audit trail"),
    "Security, data protection and compliance": ("security", "compliance", "rbi",
                                                 "gdpr", "dpdp", "data protection",
                                                 "privacy", "rbac", "penetration",
                                                 "escrow", "availability", "uptime"),
    "Evidence and references": ("reference", "case study", "client", "testimonial",
                                "credential"),
    "Commercials": ("cost", "price", "pricing", "financial", "commercial", "fee",
                    "budget", "discount"),
    "Assumptions, risks and exclusions": ("assumption", "risk", "exclusion", "out of "
                                          "scope", "dependency"),
}

#: The section a requirement belongs to when its rendered form already implies one.
#: Used to break keyword ties and as the fallback when nothing matches.
_FORM_AFFINITY: dict[DeliverableForm, str] = {
    DeliverableForm.GANTT: "Delivery plan and timeline",
    DeliverableForm.COSTING: "Commercials",
    DeliverableForm.CHART: "Recommended approach",
    DeliverableForm.MATRIX: "Governance and assurance",
    DeliverableForm.TABLE: "Team and resourcing",
    DeliverableForm.APPENDIX: "Submission compliance",
}

_SECTION_KEYWORDS: dict[str, re.Pattern[str]] = {
    title: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")",
                      re.I)
    for title, keywords in _SECTION_KEYWORD_SOURCES.items()
}

#: Where anything unmatched goes. Its existence is what guarantees zero orphans.
_CATCH_ALL = ("Additional requirements",
              "Requirements not covered by another section",
              DeliverableForm.PROSE, 400)

_SUBMISSION_SECTION = ("Submission compliance",
                       "Formalities, formats and submission mechanics",
                       DeliverableForm.APPENDIX, 250)


class ResponseArchitect:
    """Builds the response outline. One public method: design()."""

    def design(
        self,
        requirements: list[Requirement],
        buyer: BuyerProfile,
        themes: list[WinTheme] | None = None,
        mode: OutlineMode | None = None,
    ) -> ResponseOutline:
        mode = mode or self.choose_mode(buyer)
        themes = [t for t in (themes or []) if not t.dropped]

        if mode is OutlineMode.COMPLIANCE:
            sections = self._compliance_sections(requirements)
        else:
            sections = self._narrative_sections(requirements)

        self._assign_themes(sections, themes, requirements)
        outline = ResponseOutline(mode=mode, sections=sections)

        orphans = outline.orphans([r.id for r in requirements])
        if orphans:  # unreachable by construction; a loud failure beats a silent drop
            raise AssertionError(f"outline left requirements unplaced: {orphans}")
        return outline

    # --- mode -----------------------------------------------------------------------

    @staticmethod
    def choose_mode(buyer: BuyerProfile) -> OutlineMode:
        """Mirror the buyer's structure when they demand it; otherwise tell a story."""
        blob = " ".join(buyer.submission_rules)
        return (OutlineMode.COMPLIANCE if _COMPLIANCE_SIGNALS.search(blob)
                else OutlineMode.NARRATIVE)

    # --- compliance mode ------------------------------------------------------------

    @staticmethod
    def _compliance_sections(requirements: list[Requirement]) -> list[OutlineSection]:
        """One section per source section, in the buyer's own order."""
        grouped: dict[str, list[Requirement]] = {}
        for r in requirements:
            grouped.setdefault(r.source_section or "Unnumbered", []).append(r)

        def sort_key(section: str) -> tuple:
            parts = re.findall(r"\d+", section)
            return (0, [int(p) for p in parts]) if parts else (1, [], section)

        sections: list[OutlineSection] = []
        for index, key in enumerate(sorted(grouped, key=sort_key)):
            members = grouped[key]
            sections.append(OutlineSection(
                id=f"S-{index + 1:02d}",
                order_index=index,
                title=f"Response to section {key}",
                purpose=f"Answer every requirement raised in the buyer's section {key}",
                requirement_ids=[r.id for r in members],
                deliverable_form=ResponseArchitect._dominant_form(members),
                target_words=max(250, 120 * len(members)),
                source_hints=[key],
            ))
        return sections

    # --- narrative mode -------------------------------------------------------------

    def _narrative_sections(self, requirements: list[Requirement]) -> list[OutlineSection]:
        buckets: dict[str, list[Requirement]] = {title: [] for title, *_ in _NARRATIVE_SPINE}
        buckets[_SUBMISSION_SECTION[0]] = []
        buckets[_CATCH_ALL[0]] = []

        for r in requirements:
            buckets[self._best_section(r)].append(r)

        spine = [*_NARRATIVE_SPINE, _SUBMISSION_SECTION, _CATCH_ALL]
        sections: list[OutlineSection] = []
        index = 0
        for title, purpose, form, words in spine:
            members = buckets[title]
            # The executive summary is always written even with nothing assigned to it;
            # every other empty section is dropped rather than padded.
            if not members and title != "Executive summary":
                continue
            sections.append(OutlineSection(
                id=f"S-{index + 1:02d}",
                order_index=index,
                title=title,
                purpose=purpose,
                requirement_ids=[r.id for r in members],
                deliverable_form=self._dominant_form(members) if members else form,
                target_words=max(words, 110 * len(members)),
            ))
            index += 1
        return sections

    @staticmethod
    def _best_section(requirement: Requirement) -> str:
        """Score the requirement against each section's keywords; ties go to the spine."""
        from src.models.schemas import ReqType

        if requirement.req_type is ReqType.SUBMISSION_RULE:
            return _SUBMISSION_SECTION[0]

        blob = requirement.text
        affine = _FORM_AFFINITY.get(requirement.deliverable_form)

        best_title, best_score = _CATCH_ALL[0], 0.0
        for title, pattern in _SECTION_KEYWORDS.items():
            score = float(len({m.group(0).lower() for m in pattern.finditer(blob)}))
            # Break ties towards the section matching the form this requirement will be
            # rendered in. "Pricing schedule" hits both pricing and schedule; its form
            # is COSTING, so it belongs in Commercials, not in the timeline.
            if title == affine:
                score += 0.5
            if score > best_score:
                best_title, best_score = title, score

        if best_score:
            return best_title
        return affine or _CATCH_ALL[0]

    # --- shared ---------------------------------------------------------------------

    @staticmethod
    def _dominant_form(members: list[Requirement]) -> DeliverableForm:
        """The form most of a section's requirements call for, prose as the tie-break."""
        if not members:
            return DeliverableForm.PROSE
        counts: dict[DeliverableForm, int] = {}
        for r in members:
            counts[r.deliverable_form] = counts.get(r.deliverable_form, 0) + 1
        top = max(counts.values())
        winners = [f for f, c in counts.items() if c == top]
        return DeliverableForm.PROSE if DeliverableForm.PROSE in winners else winners[0]

    @staticmethod
    def _assign_themes(sections: list[OutlineSection], themes: list[WinTheme],
                       requirements: list[Requirement]) -> None:
        """Carry each theme into the sections holding the requirements it threads."""
        by_id = {r.id: r for r in requirements}
        for section in sections:
            for theme in themes:
                covered = set(theme.requirement_ids_covered) & set(section.requirement_ids)
                if covered:
                    section.themes_to_carry.append(theme.id)
        # The executive summary carries every surviving theme: it is the narrative spine.
        if sections and themes:
            summary = next((s for s in sections if s.title == "Executive summary"), None)
            if summary is not None:
                summary.themes_to_carry = [t.id for t in themes]
        _ = by_id  # kept for future scoring by requirement priority


def compliance_skeleton(outline: ResponseOutline, requirements: list[Requirement]
                        ) -> list[dict]:
    """The compliance matrix skeleton the outline emits as a by-product."""
    placement = {
        rid: s.id for s in outline.sections for rid in s.requirement_ids
    }
    return [
        {
            "requirement_id": r.id,
            "requirement_text": r.text,
            "priority": r.priority.value,
            "section_id": placement.get(r.id),
        }
        for r in sorted(requirements, key=lambda r: (r.priority is not Priority.MANDATORY, r.id))
    ]
