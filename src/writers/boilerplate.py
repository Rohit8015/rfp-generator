"""Boilerplate assembler — Phase 7. DETERMINISTIC: zero LLM calls.

Handles APPENDIX and template sections by pure template fill from data/templates.
All output carries provenance kind TEMPLATE.

Templates are selected by name, not by similarity search. Boilerplate is chosen by what
a section IS, and a retrieval mistake here would silently swap one legal appendix for
another. Placeholders that cannot be filled are left visible as [[NAME]] and reported,
rather than quietly deleted -- an unfilled placeholder in a draft is a prompt to a
human, whereas a silently removed one is a hole nobody notices.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.models.schemas import (
    BuyerProfile,
    GeneratedSection,
    OutlineSection,
    ProvenanceKind,
    SectionStatus,
)
from src.utils import provenance

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")

#: Section title fragment -> template stem. Ordered; first match wins.
TEMPLATE_ROUTES: list[tuple[str, str]] = [
    ("assumption", "tmpl_assumptions"),
    ("exclusion", "tmpl_exclusions"),
    ("out of scope", "tmpl_exclusions"),
    ("compliance matrix", "tmpl_compliance_matrix"),
    ("about", "tmpl_about_us"),
    ("cover", "tmpl_cover_page"),
    ("submission", "tmpl_cover_page"),
]


class BoilerplateWriter:
    """Fills a template for a section. One public method: write()."""

    def __init__(self, settings=None) -> None:
        if settings is None:
            from config import get_settings

            settings = get_settings()
        self.settings = settings
        self.template_dir = Path(settings.data_path) / "templates"

    # --- public ---------------------------------------------------------------------

    def write(
        self,
        section: OutlineSection,
        buyer: BuyerProfile | None = None,
        values: dict[str, str] | None = None,
    ) -> GeneratedSection:
        template = self._select(section)
        if template is None:
            return self._empty(section, "no template matches this section")

        body, unfilled = self._fill(template.read_text(encoding="utf-8"),
                                    self._values(buyer, values))
        content = f"## {section.title}\n\n{body.strip()}\n"
        if unfilled:
            content += (
                "\n> Placeholders awaiting input: "
                + ", ".join(f"[[{u}]]" for u in unfilled)
                + "\n"
            )

        generated = GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md=content,
            sentences=provenance.record_sentences(
                section.id, content, ProvenanceKind.TEMPLATE
            ),
            status=SectionStatus.DRAFTED,
        )
        return generated

    # --- internals ------------------------------------------------------------------

    def _select(self, section: OutlineSection) -> Path | None:
        """Route by section identity. Never by similarity."""
        haystack = f"{section.title} {section.purpose}".lower()
        for fragment, stem in TEMPLATE_ROUTES:
            if fragment in haystack:
                candidate = self.template_dir / f"{stem}.md"
                if candidate.is_file():
                    return candidate
        return None

    @staticmethod
    def _values(buyer: BuyerProfile | None, extra: dict[str, str] | None
                ) -> dict[str, str]:
        values: dict[str, str] = {}
        if buyer and buyer.audience_roles:
            values["CLIENT_NAME"] = buyer.audience_roles[0]
        values.update(extra or {})
        return values

    @staticmethod
    def _fill(template: str, values: dict[str, str]) -> tuple[str, list[str]]:
        """Substitute placeholders. Unfilled ones stay visible."""
        unfilled: list[str] = []

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in values:
                return values[name]
            unfilled.append(name)
            return f"[[{name}]]"

        return _PLACEHOLDER.sub(replace, template), sorted(set(unfilled))

    @staticmethod
    def _empty(section: OutlineSection, reason: str) -> GeneratedSection:
        return GeneratedSection(
            section_id=section.id,
            title=section.title,
            deliverable_form=section.deliverable_form,
            content_md="",
            sentences=[],
            status=SectionStatus.ESCALATED,
            asset_paths=[],
        )
