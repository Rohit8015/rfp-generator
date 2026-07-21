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


def test_highlighter_preserves_markdown_line_structure() -> None:
    """Regression: newlines were replaced with <br>, so a heading swallowed the body.

    A 20,000-character section body ended up inside a single <h2> at 36px, which made
    the primary deliverable unreadable.
    """
    import app.dashboard as dashboard

    body = "We deliver in phases."
    section = GeneratedSection(
        section_id="S-01", title="Approach", deliverable_form=DeliverableForm.PROSE,
        content_md=f"## Approach\n\n{body}\n\nA second paragraph follows.\n",
        sentences=[ProvenanceRecord(section_id="S-01", sentence_index=0, sentence=body,
                                    kind=ProvenanceKind.ADAPTED, source_ids=["HQ-001"])],
    )
    html = dashboard._highlight(section)
    assert "<br>" not in html, "line structure must survive for markdown to parse"
    assert "\n" in html
    lines = html.splitlines()
    assert lines[0].strip() == "## Approach", "the heading must stay on its own line"
    assert any(line.strip() == "" for line in lines), "blank lines separate blocks"


def test_highlighter_leaves_table_rows_intact() -> None:
    """Regression: wrapping a row in a span stopped it being a table row, so tables
    rendered as literal pipe-delimited text.
    """
    import app.dashboard as dashboard

    row = "| Technical | 35% | Workshop |"
    section = GeneratedSection(
        section_id="S-03", title="Criteria", deliverable_form=DeliverableForm.TABLE,
        content_md=f"## Criteria\n\n| Criterion | Weight | Method |\n|---|---|---|\n{row}\n",
        sentences=[ProvenanceRecord(section_id="S-03", sentence_index=0, sentence=row,
                                    kind=ProvenanceKind.SYNTHESIZED,
                                    source_ids=["HQ-001"])],
    )
    html = dashboard._highlight(section)
    for line in html.splitlines():
        if line.strip().startswith("|"):
            assert "<span" not in line, f"a span inside a table row breaks it: {line}"
    assert row in html


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
