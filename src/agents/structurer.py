"""A1 Document Structurer — Phase 3.

In: RFP file path. Out: DocumentTree (nested sections, numbering, page refs, raw text).

Deterministic parse first: heading styles and numbering regex do the work. The model is
used only to title a block that has none, and only when a provider is available -- an
untitled block falls back to a derived label rather than failing the run, so the
structurer keeps working offline.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.models.schemas import DocumentNode, DocumentTree
from src.utils import docparse

log = logging.getLogger(__name__)

#: "## 2.1 Mandatory Requirements" -> level 2, numbering "2.1", title "Mandatory..."
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
#: Leading numbering inside a heading: "2.1 Scope", "4. Submission", "A. Annexure"
_NUMBERING = re.compile(r"^\s*((?:\d+|[A-Z])(?:\.\d+)*)[.)]?\s+(.*)$")
_PAGE = re.compile(r"<!--page:(\d+)-->")

MAX_TITLE_WORDS = 14


class Structurer:
    """Parses an RFP into a DocumentTree. One public method: parse()."""

    def __init__(self, provider=None, use_llm: bool = True) -> None:
        self._provider = provider
        self.use_llm = use_llm

    # --- public ---------------------------------------------------------------------

    def parse(self, path: Path | str) -> DocumentTree:
        path = Path(path)
        raw = docparse.read_text(path)
        page_index = self._page_index(raw)
        text = docparse.strip_page_markers(raw)

        flat = self._flat_sections(text, page_index)
        if not flat:
            # No headings at all: the whole document is one node.
            flat = [DocumentNode(id="n0", title=None, text=text.strip(), level=1)]

        self._label_untitled(flat)
        roots = self._nest(flat)

        title = flat[0].title if flat and flat[0].level == 1 else None
        return DocumentTree(
            source_path=str(path),
            title=title,
            roots=roots,
            page_count=max(page_index.values()) if page_index else None,
        )

    # --- internals ------------------------------------------------------------------

    @staticmethod
    def _page_index(raw: str) -> dict[int, int]:
        """Character offset -> page number, for documents that carry page markers."""
        return {m.start(): int(m.group(1)) for m in _PAGE.finditer(raw)}

    @staticmethod
    def _page_for(offset: int, page_index: dict[int, int]) -> int | None:
        if not page_index:
            return None
        page = None
        for pos, num in sorted(page_index.items()):
            if pos <= offset:
                page = num
            else:
                break
        return page

    def _flat_sections(self, text: str, page_index: dict[int, int]) -> list[DocumentNode]:
        """One node per heading, carrying the body up to the next heading."""
        matches = list(_MD_HEADING.finditer(text))
        nodes: list[DocumentNode] = []

        # Text before the first heading becomes a preamble node.
        if matches and matches[0].start() > 0:
            preamble = text[: matches[0].start()].strip()
            if preamble:
                nodes.append(DocumentNode(
                    id="n0", numbering=None, title=None, text=preamble, level=1,
                    page=self._page_for(0, page_index),
                ))

        for i, m in enumerate(matches):
            level = len(m.group(1))
            heading = m.group(2).strip()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end():body_end].strip()

            numbering, title = None, heading
            nm = _NUMBERING.match(heading)
            if nm:
                numbering, title = nm.group(1), nm.group(2).strip()

            nodes.append(DocumentNode(
                id=f"n{len(nodes)}",
                numbering=numbering,
                title=title or None,
                text=body,
                level=level,
                page=self._page_for(m.start(), page_index),
            ))
        return nodes

    def _label_untitled(self, nodes: list[DocumentNode]) -> None:
        """Give untitled blocks a title. The model is the last resort, not the first."""
        for node in [n for n in nodes if not n.title and n.text.strip()]:
            derived = self._derive_title(node.text)
            if derived:
                node.title = derived

        remaining = [n for n in nodes if not n.title and n.text.strip()]
        if not remaining:
            return
        if not self.use_llm:
            self._fallback_titles(remaining)
            return

        try:
            provider = self._get_provider()
        except Exception as exc:  # noqa: BLE001 - running offline is a supported state
            log.info("no provider for block labelling; using fallback titles: %s", exc)
            self._fallback_titles(remaining)
            return

        prompts = [
            "Give a short section title, at most eight words, for this excerpt from a "
            "request for proposal. Reply with the title only: no quotes, no preamble.\n\n"
            f"{n.text[:1200]}"
            for n in remaining
        ]
        try:
            responses = provider.generate_many(prompts, tier="cheap")
        except Exception as exc:  # noqa: BLE001 - never fail a parse on a provider fault
            log.warning("block labelling failed; using fallback titles: %s", exc)
            self._fallback_titles(remaining)
            return

        for node, resp in zip(remaining, responses):
            title = docparse.normalize(resp.text).strip('"').strip()
            title = " ".join(title.split()[:MAX_TITLE_WORDS])
            node.title = title or "Untitled section"
            node.labelled_by_llm = bool(title)

    @staticmethod
    def _fallback_titles(nodes: list[DocumentNode]) -> None:
        for n in nodes:
            n.title = "Untitled section"

    @staticmethod
    def _derive_title(body: str) -> str | None:
        """Use the first short line as a title when it reads like one."""
        for line in body.splitlines():
            line = docparse.normalize(line)
            if not line:
                continue
            if len(line.split()) <= MAX_TITLE_WORDS and not line.endswith((".", ";", ",")):
                return line.rstrip(":")
            return None
        return None

    @staticmethod
    def _nest(flat: list[DocumentNode]) -> list[DocumentNode]:
        """Turn the flat heading list into a tree using heading levels."""
        roots: list[DocumentNode] = []
        stack: list[DocumentNode] = []
        for node in flat:
            while stack and stack[-1].level >= node.level:
                stack.pop()
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)
        return roots

    def _get_provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider
