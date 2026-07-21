"""Phase 11 acceptance test — dashboard.

Streamlit rendering is not unit-testable without a browser driver, so these tests cover
what can break silently: the module must import, every provenance kind must have a
colour, and the highlighter must wrap real sentences without corrupting the text.
"""

from __future__ import annotations

from pathlib import Path

from src.models.schemas import (
    DeliverableForm,
    GeneratedSection,
    ProvenanceKind,
    ProvenanceRecord,
)

ROOT = Path(__file__).parent.parent


def test_dashboard_imports() -> None:
    import app.dashboard as dashboard

    assert callable(dashboard.main)


def test_every_provenance_kind_has_a_colour() -> None:
    """A missing colour raises a KeyError mid-render, in front of an audience."""
    import app.dashboard as dashboard

    for kind in ProvenanceKind:
        assert kind in dashboard.PROVENANCE_COLOURS, f"{kind.value} has no colour"
        foreground, background, meaning = dashboard.PROVENANCE_COLOURS[kind]
        assert foreground.startswith("#") and background.startswith("#")
        assert meaning, f"{kind.value} has no explanation for the legend"


def test_highlighter_wraps_sentences_without_losing_text() -> None:
    import app.dashboard as dashboard

    section = GeneratedSection(
        section_id="S-01", title="Approach", deliverable_form=DeliverableForm.PROSE,
        content_md="## Approach\n\nWe deliver in phases. A human must confirm scope.\n",
        sentences=[
            ProvenanceRecord(section_id="S-01", sentence_index=0,
                             sentence="We deliver in phases.",
                             kind=ProvenanceKind.ADAPTED, source_ids=["HQ-001"]),
            ProvenanceRecord(section_id="S-01", sentence_index=1,
                             sentence="A human must confirm scope.",
                             kind=ProvenanceKind.STAKEHOLDER),
        ],
    )
    html = dashboard._highlight(section)
    assert "We deliver in phases." in html
    assert "A human must confirm scope." in html
    assert "ADAPTED" in html and "STAKEHOLDER" in html
    assert "HQ-001" in html, "source ids should appear in the tooltip"


def test_highlighter_handles_a_section_with_no_records() -> None:
    import app.dashboard as dashboard

    empty = GeneratedSection(section_id="S-01", title="T",
                             deliverable_form=DeliverableForm.PROSE,
                             content_md="## T\n\nSome text.\n")
    assert "Some text." in dashboard._highlight(empty)


def test_dashboard_never_sends_anything() -> None:
    """CLAUDE.md: drafts only. The UI exports files; it must not transmit."""
    source = (ROOT / "app" / "dashboard.py").read_text(encoding="utf-8").lower()
    for forbidden in ["smtplib", "sendmail", "requests.post", "httpx.post"]:
        assert forbidden not in source, f"dashboard.py references {forbidden}"
