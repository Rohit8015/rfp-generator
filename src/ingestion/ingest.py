"""Corpus ingestion — Phase 2.

Contract: chunks and embeds knowledge_base, historical_rfps, proof_library and templates
into Chroma, and builds a BM25 index over the same chunks. Idempotent: re-running
rebuilds cleanly rather than duplicating.

Hard boundary (CLAUDE.md data hygiene): these four directories are the ONLY sources.
data/eval, data/incoming and data/archive_xcd are never read. Ingesting the sealed
held-out set would invalidate every metric the project reports, so the allowed set is a
module constant and is asserted in tests rather than left to convention.

Chunking is source-aware:
- A historical Q&A pair is one chunk. The pair is the unit a human would reuse.
- A proof point is one chunk. Splitting a claim from its evidence would let the
  retriever surface an unevidenced claim.
- A knowledge base document is split on markdown headings, then on size.
- A template is one chunk; boilerplate is filled whole.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
import shutil
from pathlib import Path

from config import get_settings
from src.models.schemas import Chunk, ChunkKind

log = logging.getLogger(__name__)

#: The only directories ingestion may read. Everything else is out of bounds.
INGESTIBLE_DIRS = ("knowledge_base", "historical_rfps", "proof_library", "templates")

#: Never read, at any cost. The sealed test set and the archived European material.
FORBIDDEN_DIRS = ("eval", "incoming", "archive_xcd")

COLLECTION = "rfp_corpus"

MAX_CHARS = 1400
OVERLAP_CHARS = 180
#: Sections below this are merged forward. A bare heading with no body ("## Our
#: Verticals") embeds to noise and would compete with real content at retrieval time.
MIN_CHARS = 320

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$", re.MULTILINE)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lexical tokens for BM25. Lowercased alphanumerics keep GDPR/SOC/PSD2 intact."""
    return _TOKEN.findall(text.lower())


# --------------------------------------------------------------------------------------
# Chunkers
# --------------------------------------------------------------------------------------


def _split_long(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS
                ) -> list[str]:
    """Split on paragraph boundaries, with overlap so a fact is not cut in half."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        if len(buf) + len(para) + 2 <= max_chars:
            buf = f"{buf}\n\n{para}".strip()
            continue
        if buf:
            parts.append(buf)
            buf = (buf[-overlap:] + "\n\n" + para).strip()
        else:
            # A single oversized paragraph; hard-split it.
            for i in range(0, len(para), max_chars - overlap):
                parts.append(para[i : i + max_chars])
            buf = ""
    if buf:
        parts.append(buf)
    return [p for p in parts if p.strip()]


def chunk_knowledge_base(path: Path) -> list[Chunk]:
    """Split a KB document on headings. source_id is the KB-0NN prefix in the filename."""
    text = path.read_text(encoding="utf-8")
    source_id = path.stem.split("_")[0]  # "KB-003_data_protection" -> "KB-003"
    doc_title = ""
    m = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
    if m:
        doc_title = m.group(1).strip()

    # Cut at every heading of level 2 or deeper; keep the heading with its body.
    positions = [(mm.start(), mm.group(2).strip()) for mm in _HEADING.finditer(text)
                 if len(mm.group(1)) >= 2]
    sections: list[tuple[str, str]] = []
    if not positions:
        sections = [(doc_title, text)]
    else:
        if positions[0][0] > 0:
            sections.append((doc_title, text[: positions[0][0]]))
        for i, (start, heading) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            sections.append((heading, text[start:end]))

    # Merge undersized sections forward. A heading with no body of its own carries no
    # retrievable content, and its heading text belongs with the subsection beneath it.
    merged: list[tuple[str, str]] = []
    buf_heading, buf_body = "", ""
    for heading, body in sections:
        buf_heading = buf_heading or heading
        buf_body = f"{buf_body}\n\n{body}".strip()
        if len(buf_body) >= MIN_CHARS:
            merged.append((buf_heading, buf_body))
            buf_heading, buf_body = "", ""
    if buf_body:
        if merged:  # trailing remnant joins the previous block rather than standing alone
            prev_heading, prev_body = merged[-1]
            merged[-1] = (prev_heading, f"{prev_body}\n\n{buf_body}".strip())
        else:
            merged.append((buf_heading, buf_body))

    chunks: list[Chunk] = []
    for heading, body in merged:
        for piece in _split_long(body):
            chunks.append(Chunk(
                id=f"{source_id}#{len(chunks):02d}",
                source_id=source_id,
                kind=ChunkKind.KNOWLEDGE_BASE,
                text=piece,
                source_ref=path.name,
                title=f"{doc_title} — {heading}".strip(" —") if heading else doc_title,
            ))
    return chunks


def chunk_historical_qa(path: Path) -> list[Chunk]:
    """One chunk per Q&A pair. source_id is the HQ-0NN record id."""
    obj = json.loads(path.read_text(encoding="utf-8"))
    records = next(v for v in obj.values() if isinstance(v, list)) if isinstance(obj, dict) else obj
    chunks: list[Chunk] = []
    for r in records:
        rid = r["id"]
        chunks.append(Chunk(
            id=rid,
            source_id=rid,
            kind=ChunkKind.HISTORICAL_QA,
            text=f"Q: {r['question']}\n\nA: {r['answer']}",
            source_ref=path.name,
            title=r["question"],
            tags=list(r.get("tags", [])),
            metadata={
                k: str(r[k]) for k in
                ("category", "owner_dept", "client_industry", "status", "date_approved")
                if r.get(k) is not None
            },
        ))
    return chunks


def chunk_proof_points(path: Path) -> list[Chunk]:
    """One chunk per proof point. Claim and evidence are never separated."""
    obj = json.loads(path.read_text(encoding="utf-8"))
    records = next(v for v in obj.values() if isinstance(v, list)) if isinstance(obj, dict) else obj
    chunks: list[Chunk] = []
    for r in records:
        body = f"Claim: {r['claim']}\n\nEvidence: {r['evidence']}"
        if r.get("verifiable_source"):
            body += f"\n\nSource: {r['verifiable_source']}"
        chunks.append(Chunk(
            id=r["id"],
            source_id=r["id"],
            kind=ChunkKind.PROOF_POINT,
            text=body,
            source_ref=path.name,
            title=r["claim"][:120],
            tags=list(r.get("covers_tags", [])),
            metadata={"type": str(r.get("type", "")), "strength": str(r.get("strength", ""))},
        ))
    return chunks


def chunk_template(path: Path) -> list[Chunk]:
    """A template is one chunk. Boilerplate is filled whole, not in pieces."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    source_id = f"TMPL-{path.stem.replace('tmpl_', '')}"
    m = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
    return [Chunk(
        id=source_id,
        source_id=source_id,
        kind=ChunkKind.TEMPLATE,
        text=text,
        source_ref=path.name,
        title=m.group(1).strip() if m else path.stem,
    )]


# --------------------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------------------


def collect_chunks(data_path: Path | None = None) -> list[Chunk]:
    """Walk the four permitted directories and chunk everything in them."""
    data_path = data_path or get_settings().data_path
    chunks: list[Chunk] = []

    kb = data_path / "knowledge_base"
    for p in sorted(kb.glob("*.md")):
        chunks.extend(chunk_knowledge_base(p))

    hq = data_path / "historical_rfps"
    for p in sorted(hq.glob("*.json")):
        chunks.extend(chunk_historical_qa(p))

    pl = data_path / "proof_library"
    for p in sorted(pl.glob("*.json")):
        chunks.extend(chunk_proof_points(p))

    tm = data_path / "templates"
    for p in sorted(tm.glob("*.md")):
        chunks.extend(chunk_template(p))

    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"duplicate chunk ids: {sorted(dupes)}")
    return chunks


# --------------------------------------------------------------------------------------
# Index build
# --------------------------------------------------------------------------------------


class Ingestor:
    """Builds the Chroma and BM25 indices. One public method: run()."""

    def __init__(self, settings=None, provider=None) -> None:
        self.settings = settings or get_settings()
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            from src.llm.provider import get_provider

            self._provider = get_provider()
        return self._provider

    def run(self, rebuild: bool = True) -> dict[str, object]:
        """Chunk, embed, and write both indices. Returns a summary."""
        chunks = collect_chunks(self.settings.data_path)
        if not chunks:
            raise ValueError("no chunks collected; is the corpus present under data/?")

        log.info("embedding %d chunks with %s", len(chunks), self.settings.embedding_model)
        vectors = self.provider.embed([c.text for c in chunks])

        self._write_chroma(chunks, vectors, rebuild=rebuild)
        self._write_bm25(chunks)

        by_kind: dict[str, int] = {}
        for c in chunks:
            by_kind[c.kind.value] = by_kind.get(c.kind.value, 0) + 1
        return {
            "chunks": len(chunks),
            "sources": len({c.source_id for c in chunks}),
            "by_kind": by_kind,
            "dimensions": len(vectors[0]),
            "chroma_path": str(self.settings.chroma_path),
            "bm25_path": str(self.settings.bm25_index_path),
        }

    def _write_chroma(self, chunks: list[Chunk], vectors: list[list[float]],
                      rebuild: bool) -> None:
        import chromadb

        path = self.settings.chroma_path
        if rebuild and path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(path=str(path))
        try:
            client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001 - absent collection is the normal case
            pass
        collection = client.create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        collection.add(
            ids=[c.id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[{
                "source_id": c.source_id,
                "kind": c.kind.value,
                "source_ref": c.source_ref,
                "title": c.title,
                "tags": ",".join(c.tags),
            } for c in chunks],
        )

    def _write_bm25(self, chunks: list[Chunk]) -> None:
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(c.text) for c in chunks]
        bm25 = BM25Okapi(corpus)
        path = self.settings.bm25_index_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"bm25": bm25, "chunks": [c.model_dump() for c in chunks]}, f)


def load_bm25(settings=None):
    """Return (bm25_index, [Chunk]) from the pickled index."""
    settings = settings or get_settings()
    with settings.bm25_index_path.open("rb") as f:
        payload = pickle.load(f)
    return payload["bm25"], [Chunk.model_validate(d) for d in payload["chunks"]]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = Ingestor().run()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
