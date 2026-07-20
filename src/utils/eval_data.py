"""Labelled evaluation data loader — Phase 3.

CLAUDE.md: the contracts in src/models/schemas.py are authoritative because they drive
behaviour; dataset labels are translated here on load, never the reverse.

Two translations matter:

`deliverable_form` — the dataset labels what the client is buying (PLATFORM, AI_MODEL,
SLA). The contract labels how a section is rendered (PROSE, TABLE, GANTT), which is what
routes A9 to a writer in Phase 7. The map below is many-to-one and lossy in the direction
that does not matter: two different purchases can both be described in prose.

`req_type` — the dataset uses SHALL/SHOULD/MAY_REQUIREMENT, which is perfectly
correlated with its own `priority` field (20/9/4 either way) and so carries no
information the contract needs. The contract's six-way type is derived from the text.
`priority` is taken from the dataset directly, since those values already match.

Scoring note: extraction is scored on TEXT MATCH, not on the dataset's requirement_id.
Matching on id would reward a regex that scrapes "R-001" without understanding anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from src.models.schemas import DeliverableForm, Priority
from src.utils import docparse

#: Dataset deliverable_form -> contract deliverable_form (how the section renders).
DELIVERABLE_FORM_MAP: dict[str, DeliverableForm] = {
    # Things described in narrative prose
    "PLATFORM": DeliverableForm.PROSE,
    "SYSTEM": DeliverableForm.PROSE,
    "SERVICE": DeliverableForm.PROSE,
    "INTEGRATION": DeliverableForm.PROSE,
    "AI_MODEL": DeliverableForm.PROSE,
    "AI_SYSTEM": DeliverableForm.PROSE,
    "AI_CHATBOT": DeliverableForm.PROSE,
    "BLOCKCHAIN": DeliverableForm.PROSE,
    "AR_VR": DeliverableForm.PROSE,
    "MOBILE": DeliverableForm.PROSE,
    "UX_UI": DeliverableForm.PROSE,
    "FEATURE": DeliverableForm.PROSE,
    "SECURITY": DeliverableForm.PROSE,
    "GOVERNANCE": DeliverableForm.PROSE,
    "COMPLIANCE": DeliverableForm.PROSE,
    # Things that render as a table or matrix
    "SLA": DeliverableForm.TABLE,
    "ANALYTICS": DeliverableForm.TABLE,
    "DASHBOARD": DeliverableForm.TABLE,
    "REPORT": DeliverableForm.TABLE,
    "REFERENCE": DeliverableForm.TABLE,
    # Things that render as a schedule
    "PLAN": DeliverableForm.GANTT,
    "DEADLINE": DeliverableForm.GANTT,
    # Things that render as an appendix or attachment
    "DOCUMENT": DeliverableForm.APPENDIX,
    "SUBMISSION": DeliverableForm.APPENDIX,
}


class LabelledRequirement(BaseModel):
    """One hand-labelled requirement, with dataset labels already translated."""

    requirement_id: str
    source_section: str
    text: str
    priority: Priority
    deliverable_form: DeliverableForm
    dataset_req_type: str
    dataset_deliverable_form: str
    notes: str = ""
    reuse_bucket: str = ""


def load_labelled_requirements(path: Path | str | None = None
                               ) -> tuple[str, list[LabelledRequirement]]:
    """Return (rfp_id, requirements) from the labelled set."""
    if path is None:
        from config import get_settings

        path = get_settings().data_path / "eval" / "requirements_labelled.json"
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for r in obj["requirements"]:
        raw_form = r["deliverable_form"]
        if raw_form not in DELIVERABLE_FORM_MAP:
            raise ValueError(
                f"unmapped dataset deliverable_form {raw_form!r} on "
                f"{r['requirement_id']}; add it to DELIVERABLE_FORM_MAP"
            )
        out.append(LabelledRequirement(
            requirement_id=r["requirement_id"],
            source_section=str(r["source_section"]),
            text=r["text"],
            priority=Priority(r["priority"]),
            deliverable_form=DELIVERABLE_FORM_MAP[raw_form],
            dataset_req_type=r["req_type"],
            dataset_deliverable_form=raw_form,
            notes=r.get("notes", ""),
            reuse_bucket=r.get("reuse_bucket", ""),
        ))
    return obj["rfp_id"], out


# --------------------------------------------------------------------------------------
# Text matching, used to score extraction
# --------------------------------------------------------------------------------------

_STOP = {
    "the", "a", "an", "of", "to", "for", "and", "with", "in", "on", "by", "is", "are",
    "be", "as", "at", "or", "that", "this", "it", "its", "from", "vendor", "supplier",
    "bidder", "shall", "must", "should", "may", "will", "provide", "include", "must",
}


def content_tokens(text: str) -> set[str]:
    t = docparse.normalize(text).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return {w for w in t.split() if w and w not in _STOP and len(w) > 1}


def similarity(a: str, b: str) -> float:
    """Jaccard over content tokens.

    Deliberately lexical. An embedding-based match would let a vaguely related sentence
    count as a hit and quietly inflate recall, which is the metric the phase gates on.
    """
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def containment(a: str, b: str) -> float:
    """Share of the shorter item's tokens present in the longer one."""
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & large) / len(small)
