"""A2 Requirement Extractor — Phase 3.

In: DocumentTree. Out: list[Requirement] with req_type, priority, deliverable_form and
cue_evidence. A deterministic Shipley cue-word pass is unioned with an LLM pass for
implied deliverables, then deduped. Gate: >=90% recall, 100% MANDATORY recall.

Design notes:

- The cue pass carries the MANDATORY gate. Recall of must-win requirements cannot depend
  on a model being reachable, so shall/must/required extraction is pure regex and runs
  even with no provider configured.
- The LLM pass only adds IMPLIED_DELIVERABLE items -- obligations a buyer states without
  a cue word ("we expect two references"). It can never remove or downgrade a cue-pass
  requirement, so a bad generation degrades precision, never MANDATORY recall.
- `deliverable_form` here is the CONTRACT enum (PROSE/TABLE/GANTT/...), which decides
  which writer renders the section in Phase 7. It is deliberately not the dataset's
  enum, which describes what the client is buying. See CLAUDE.md label mapping.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from src.models.schemas import (
    DeliverableForm,
    DocumentTree,
    Priority,
    Requirement,
    ReqType,
)
from src.utils import docparse

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Shipley cue words. Order matters: the first matching band wins.
# --------------------------------------------------------------------------------------

_MANDATORY_CUES = r"\b(shall|must|required|mandatory|is\s+to\s+be|obligated)\b"
_WEIGHTED_CUES = r"\b(should|scored|weighted|will\s+be\s+evaluated|expected\s+to)\b"
_OPTIONAL_CUES = r"\b(may|preferred|desirable|desired|nice[-\s]to[-\s]have|optional)\b"

_PRIORITY_BANDS: list[tuple[Priority, re.Pattern[str]]] = [
    (Priority.MANDATORY, re.compile(_MANDATORY_CUES, re.I)),
    (Priority.WEIGHTED, re.compile(_WEIGHTED_CUES, re.I)),
    (Priority.NICE_TO_HAVE, re.compile(_OPTIONAL_CUES, re.I)),
]

#: Obligations expressed as a command rather than a modal: "Submit three references",
#: "Provide a timeline". Common in submission sections and invisible to a modal-only cue
#: model, which is exactly where the first version of this extractor lost recall.
_IMPERATIVE = re.compile(
    r"^\s*(submit|provide|include|attach|furnish|supply|deliver|complete|enclose|"
    r"demonstrate|describe|detail|list|specify|state|confirm|ensure)\b",
    re.I,
)
#: Declarative submission facts: "Deadline: 30 April", "Required formats: PDF".
_DECLARATIVE_RULE = re.compile(
    r"^\s*(deadline|due date|closing date|submission|required formats?|format|"
    r"validity|bid bond|emd)\b\s*[:–-]",
    re.I,
)

#: A section heading fixes the priority of everything under it. "2.1 Mandatory
#: Requirements (SHALL/REQUIRED)" makes its contents mandatory whether or not each line
#: repeats the cue word.
_SECTION_PRIORITY: list[tuple[Priority, re.Pattern[str]]] = [
    (Priority.NICE_TO_HAVE,
     re.compile(r"nice[-\s]?to[-\s]?have|optional|desirable|\bpreferred\b", re.I)),
    (Priority.MANDATORY,
     re.compile(r"\bmandatory\b|\bshall\b|\brequired\b|\bsubmission\b|"
                r"instructions to bidders", re.I)),
    (Priority.WEIGHTED,
     re.compile(r"\bweighted\b|\bscored\b|\bshould\b|\bevaluation\b", re.I)),
]

#: An explicitly numbered requirement: "**R-001**: The vendor SHALL ..."
_LABELLED_REQ = re.compile(
    r"^\s*\**\s*(?P<rid>[A-Z]{1,4}-\d{1,4})\s*\**\s*[:.–-]\s*(?P<body>.+)$",
    re.MULTILINE,
)
#: A markdown table row. Requirements often live in weighted-scoring tables.
_TABLE_ROW = re.compile(r"^\s*\|(?P<cells>.+)\|\s*$", re.MULTILINE)

_MIN_REQUIREMENT_WORDS = 4

# Section-title hints that override the type inferred from the sentence itself.
_SUBMISSION_HINTS = ("submission", "how to submit", "instructions to bidders", "annexure")
_EVAL_HINTS = ("evaluation", "scoring", "award", "weighting")

# Text hints that decide how a section will be rendered later.
#
# Matched on word boundaries, never as bare substrings. The first version used
# `hint in blob` and routed every MANDATORY requirement to APPENDIX, because the hint
# "nda" appears inside "ma-nda-tory". Short hints like sla, cv and nda make substring
# matching actively dangerous here.
_FORM_HINT_SOURCES: list[tuple[DeliverableForm, tuple[str, ...]]] = [
    (DeliverableForm.MATRIX, ("compliance matrix", "traceability matrix",
                              "requirements? matrix")),
    (DeliverableForm.GANTT, ("timeline", "milestones?", "schedule", "roadmap", "phasing",
                             "implementation plan", "project plan")),
    (DeliverableForm.COSTING, ("cost", "costs", "costing", "price", "pricing",
                               "financial", "commercials?", "budget", "fees?",
                               "rate card")),
    (DeliverableForm.CHART, ("architecture diagram", "diagrams?", "heat ?map", "charts?",
                             "dashboards?")),
    (DeliverableForm.APPENDIX, ("annexures?", "appendix", "appendices", "attachments?",
                                "templates?", "escrow", "nda",
                                "non-disclosure agreement")),
    (DeliverableForm.TABLE, ("tables?", "list of", "matrix", "kpis?", "slas?",
                             "references?", "cvs?", "team structure", "resource plan",
                             "scoring")),
]

_FORM_HINTS: list[tuple[DeliverableForm, re.Pattern[str]]] = [
    (form, re.compile(r"\b(?:" + "|".join(hints) + r")\b", re.I))
    for form, hints in _FORM_HINT_SOURCES
]


class _ImpliedItem(BaseModel):
    """One obligation the model believes is implied but carries no cue word."""

    text: str = Field(min_length=10)
    rationale: str = ""


class _ImpliedBatch(BaseModel):
    requirements: list[_ImpliedItem] = Field(default_factory=list)


class RequirementExtractor:
    """Extracts typed requirements from a DocumentTree. One public method: extract()."""

    def __init__(self, provider=None, use_llm: bool = True) -> None:
        self._provider = provider
        self.use_llm = use_llm

    # --- public ---------------------------------------------------------------------

    def extract(self, tree: DocumentTree) -> list[Requirement]:
        cue_items = self._cue_pass(tree)
        llm_items = self._llm_pass(tree, cue_items) if self.use_llm else []
        return self._union(cue_items, llm_items)

    # --- deterministic pass ---------------------------------------------------------

    def _cue_pass(self, tree: DocumentTree) -> list[Requirement]:
        found: list[Requirement] = []
        for node in tree.nodes():
            if not node.text.strip():
                continue
            section = node.numbering or node.title or node.id
            section_default = self._section_priority(node.title or "")
            for text, evidence in self._candidates(node.text):
                priority = self._priority(text)
                if priority is None:
                    # No modal cue. An explicitly numbered or tabulated item is still a
                    # requirement -- the document numbered it -- and so is an imperative
                    # or a declarative submission rule. Fall back to the priority its
                    # section heading declares.
                    explicit = evidence.startswith(("labelled", "table row"))
                    directive = bool(_IMPERATIVE.match(text) or _DECLARATIVE_RULE.match(text))
                    if not (explicit or directive):
                        continue
                    priority = section_default or (
                        Priority.MANDATORY if directive and explicit else Priority.WEIGHTED
                    )
                    evidence = f"{evidence}; no modal cue, priority from section"
                found.append(Requirement(
                    id="",  # assigned during union, once ordering is final
                    source_section=str(section),
                    text=text,
                    req_type=self._req_type(text, node.title or "", priority),
                    priority=priority,
                    deliverable_form=self._deliverable_form(text, node.title or ""),
                    cue_evidence=evidence,
                    extracted_by="cue",
                ))
        return found

    def _candidates(self, body: str) -> list[tuple[str, str]]:
        """Yield (requirement text, cue evidence) from one section body."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        # 1. Explicitly labelled requirements. The strongest signal available.
        for m in _LABELLED_REQ.finditer(body):
            text = docparse.normalize(m.group("body"))
            if self._plausible(text) and text.lower() not in seen:
                seen.add(text.lower())
                out.append((text, f"labelled {m.group('rid')}"))

        # 2. Table rows. Weighted requirements are usually tabulated.
        for m in _TABLE_ROW.finditer(body):
            cells = [docparse.normalize(c) for c in m.group("cells").split("|")]
            cells = [c for c in cells if c and not set(c) <= {"-", ":", " "}]
            if not cells:
                continue
            # The longest cell is the requirement text; the rest are id and weight.
            text = max(cells, key=len)
            if not self._plausible(text) or text.lower() in seen:
                continue
            rid = next((c for c in cells if re.fullmatch(r"[A-Z]{1,4}-\d{1,4}", c)), None)
            # A row is a requirement if it carries a cue word or if the table numbered it.
            if not rid and not any(p.search(text) for _, p in _PRIORITY_BANDS):
                continue
            seen.add(text.lower())
            out.append((text, f"table row{f' {rid}' if rid else ''}"))

        # 3. Free-text sentences: a modal cue, an imperative, or a declarative rule.
        for sentence in docparse.split_sentences(body):
            if not self._plausible(sentence) or sentence.lower() in seen:
                continue
            cue = self._cue_word(sentence)
            if cue:
                evidence = f"cue '{cue}'"
            elif _IMPERATIVE.match(sentence):
                evidence = f"imperative '{_IMPERATIVE.match(sentence).group(1).lower()}'"
            elif _DECLARATIVE_RULE.match(sentence):
                evidence = "declarative submission rule"
            else:
                continue
            seen.add(sentence.lower())
            out.append((sentence, evidence))
        return out

    @staticmethod
    def _plausible(text: str) -> bool:
        if len(text.split()) < _MIN_REQUIREMENT_WORDS:
            return False
        # Reject table separators and pure headings.
        if set(text) <= {"-", ":", "|", " "}:
            return False
        # Reject blobs that swallowed several requirements at once. A candidate naming
        # more than one requirement id is a chunk of the document, not a requirement,
        # and it poisons everything downstream: proof matching scores it against every
        # topic, and it appears in the UI as garbled concatenated text.
        if len(set(re.findall(r"\b[A-Z]{1,4}-\d{2,4}\b", text))) > 1:
            return False
        # Reject anything carrying a horizontal rule or a heading marker: those are
        # document structure that leaked into the capture.
        if re.search(r"(^|\s)---+(\s|$)|(^|\s)###?\s", text):
            return False
        return True

    @staticmethod
    def _cue_word(text: str) -> str | None:
        for _, pattern in _PRIORITY_BANDS:
            m = pattern.search(text)
            if m:
                return m.group(0).lower()
        return None

    @staticmethod
    def _priority(text: str) -> Priority | None:
        for priority, pattern in _PRIORITY_BANDS:
            if pattern.search(text):
                return priority
        return None

    @staticmethod
    def _section_priority(section_title: str) -> Priority | None:
        """Priority declared by the section heading, if it declares one."""
        for priority, pattern in _SECTION_PRIORITY:
            if pattern.search(section_title):
                return priority
        return None

    @staticmethod
    def _req_type(text: str, section_title: str, priority: Priority) -> ReqType:
        blob = f"{section_title} {text}".lower()
        if text.rstrip().endswith("?"):
            return ReqType.EXPLICIT_QUESTION
        if any(h in section_title.lower() for h in _SUBMISSION_HINTS):
            return ReqType.SUBMISSION_RULE
        if any(h in section_title.lower() for h in _EVAL_HINTS):
            return ReqType.EVAL_CRITERION
        if re.search(r"\b(submit|submission|deadline|format|prescribed|annexure|"
                     r"portal|upload)\b", blob):
            return ReqType.SUBMISSION_RULE
        if re.search(r"\b(comply|compliance|regulat|guideline|law|act\b|gdpr|rbi|"
                     r"availability|uptime|sla|penalt)\w*", blob):
            return ReqType.CONSTRAINT
        if priority is Priority.MANDATORY:
            return ReqType.SHALL_REQUIREMENT
        return ReqType.IMPLIED_DELIVERABLE

    @staticmethod
    def _deliverable_form(text: str, section_title: str) -> DeliverableForm:
        """How this requirement's answer renders. Routes A9 to a writer in Phase 7.

        The requirement text is weighted above the section heading: a costing question
        inside a section titled "Submission Requirements" is still a costing question.
        """
        for blob in (text, f"{section_title} {text}"):
            for form, pattern in _FORM_HINTS:
                if pattern.search(blob):
                    return form
        return DeliverableForm.PROSE

    # --- LLM pass -------------------------------------------------------------------

    def _llm_pass(self, tree: DocumentTree, already: list[Requirement]
                  ) -> list[Requirement]:
        """Ask for obligations that carry no cue word. Additive only."""
        try:
            provider = self._get_provider()
        except Exception as exc:  # noqa: BLE001 - offline is supported
            log.info("no provider; skipping implied-deliverable pass: %s", exc)
            return []

        known = {docparse.normalize(r.text).lower() for r in already}
        sections = [n for n in tree.nodes() if len(n.text.split()) > 25]
        if not sections:
            return []

        prompts = [self._implied_prompt(n.title or "", n.text) for n in sections]
        try:
            responses = provider.generate_many(
                prompts, tier="cheap", schema=_ImpliedBatch
            )
        except Exception as exc:  # noqa: BLE001 - never fail extraction on a model fault
            log.warning("implied-deliverable pass failed; cue results stand: %s", exc)
            return []

        out: list[Requirement] = []
        for node, resp in zip(sections, responses):
            batch = resp.parsed
            if batch is None:
                continue
            for item in batch.requirements:
                text = docparse.normalize(item.text)
                if not self._plausible(text) or text.lower() in known:
                    continue
                known.add(text.lower())
                out.append(Requirement(
                    id="",
                    source_section=str(node.numbering or node.title or node.id),
                    text=text,
                    req_type=ReqType.IMPLIED_DELIVERABLE,
                    # An implied obligation is never MANDATORY: nothing in the document
                    # says it is. Overstating priority here would corrupt the bid
                    # qualifier's mandatory-fit calculation in Phase 4.
                    priority=Priority.WEIGHTED,
                    deliverable_form=self._deliverable_form(text, node.title or ""),
                    cue_evidence=f"implied: {item.rationale[:120]}" if item.rationale
                                 else "implied",
                    extracted_by="llm",
                ))
        return out

    @staticmethod
    def _implied_prompt(title: str, body: str) -> str:
        return (
            "You are reading one section of a request for proposal.\n\n"
            "List obligations the buyer expects but has NOT written with an explicit cue "
            "word such as shall, must, should or may. These are implied deliverables: "
            "things a bidder must produce to be responsive, stated as expectations or "
            "context rather than as numbered requirements.\n\n"
            "Rules:\n"
            "- Do NOT repeat sentences that already contain shall, must, should or may.\n"
            "- Do NOT invent obligations that the text does not support.\n"
            "- If the section implies nothing, return an empty list.\n"
            "- Each item must be one sentence naming a concrete deliverable.\n\n"
            'Return JSON: {"requirements": [{"text": "...", "rationale": "..."}]}\n\n'
            f"Section title: {title}\n\nSection text:\n{body[:3000]}"
        )

    # --- union ----------------------------------------------------------------------

    def _union(self, cue_items: list[Requirement], llm_items: list[Requirement]
               ) -> list[Requirement]:
        """Merge both passes, dedupe on normalized text, and assign stable ids."""
        merged: list[Requirement] = []
        seen: dict[str, Requirement] = {}

        for item in [*cue_items, *llm_items]:
            key = self._dedupe_key(item.text)
            existing = seen.get(key)
            if existing is None:
                seen[key] = item
                merged.append(item)
                continue
            # Same requirement found twice. Record that both passes saw it, and keep the
            # stronger priority -- never let the LLM pass weaken a cue-pass MANDATORY.
            if existing.extracted_by != item.extracted_by:
                existing.extracted_by = "both"
            if self._rank(item.priority) > self._rank(existing.priority):
                existing.priority = item.priority

        return [
            r.model_copy(update={"id": f"R-{i:03d}"})
            for i, r in enumerate(merged, start=1)
        ]

    @staticmethod
    def _dedupe_key(text: str) -> str:
        """Normalize aggressively: the two passes rarely phrase a match identically."""
        t = docparse.normalize(text).lower()
        t = re.sub(r"\b(the|a|an|of|to|for|and|with|shall|must|should|may|will|vendor|"
                   r"supplier|bidder|provide|include)\b", " ", t)
        t = re.sub(r"[^a-z0-9 ]+", " ", t)
        return " ".join(sorted(set(t.split())))[:220]

    @staticmethod
    def _rank(priority: Priority) -> int:
        return {Priority.NICE_TO_HAVE: 0, Priority.WEIGHTED: 1, Priority.MANDATORY: 2}[
            priority
        ]

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider
