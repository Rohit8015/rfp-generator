"""Dataset integrity guards.

These protect the evaluation from the two failure modes that silently invalidate every
metric downstream: reading the sealed test set, and ingesting it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SEALED = DATA / "eval" / "sealed"

#: The only directories ingestion is permitted to read.
INGESTIBLE = ["knowledge_base", "historical_rfps", "proof_library", "templates"]


def test_split_file_exists_and_is_valid() -> None:
    split = json.loads((DATA / "eval" / "split.json").read_text(encoding="utf-8"))
    assert split["split_strategy"] == "BY_DOCUMENT"
    assert split["dev_count"] == len(split["dev_documents"]) == 3
    assert split["test_count"] == len(split["test_documents"]) == 2
    assert not set(split["dev_documents"]) & set(split["test_documents"])


def test_sealed_documents_are_unmodified() -> None:
    """A changed hash means the held-out set was touched and metrics are contaminated."""
    split = json.loads((DATA / "eval" / "split.json").read_text(encoding="utf-8"))
    for stem, expected in split["hashes"].items():
        path = SEALED / f"{stem}.md"
        assert path.is_file(), f"sealed file missing: {stem}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"{stem} has changed since sealing. Every metric produced after this point "
            f"must be reported as contaminated."
        )


def test_sealed_files_are_outside_ingestion_reach() -> None:
    """Ingestion reads four directories. None may contain a sealed document."""
    for folder in INGESTIBLE:
        for path in (DATA / folder).rglob("*"):
            if path.is_file():
                assert "sealed" not in path.parts, f"sealed file inside {folder}: {path}"
                assert "RFP-D" not in path.name and "RFP-E" not in path.name, (
                    f"held-out document inside an ingested directory: {path}"
                )


def test_held_out_rfps_are_not_in_incoming() -> None:
    """incoming/ is the queue of RFPs to process. A sealed RFP there would be run."""
    names = [p.name for p in (DATA / "incoming").glob("*")]
    assert not [n for n in names if "RFP-D" in n or "RFP-E" in n], (
        f"sealed RFP found in data/incoming: {names}"
    )


def test_dev_rfps_are_present() -> None:
    names = sorted(p.stem for p in (DATA / "incoming").glob("RFP-*.md"))
    assert len(names) == 3, f"expected RFP-A/B/C in incoming, found {names}"


@pytest.mark.parametrize("folder,minimum", [
    ("knowledge_base", 10), ("historical_rfps", 4), ("templates", 5), ("params", 3),
])
def test_corpus_is_populated(folder: str, minimum: int) -> None:
    n = len([p for p in (DATA / folder).glob("*") if p.is_file() and p.name != ".gitkeep"])
    assert n >= minimum, f"{folder} has {n} files, expected at least {minimum}"


def test_eval_sets_parse() -> None:
    expected = {
        "requirements_labelled.json": 33,
        "retrieval_pairs.json": 50,
        "deal_contexts.json": 6,
        "grounding_labelled.json": 40,
    }
    for name, count in expected.items():
        obj = json.loads((DATA / "eval" / name).read_text(encoding="utf-8"))
        items = next(v for v in obj.values() if isinstance(v, list)) if isinstance(obj, dict) else obj
        assert len(items) == count, f"{name}: expected {count} items, got {len(items)}"


def test_historical_qa_totals_120() -> None:
    total = 0
    for p in sorted((DATA / "historical_rfps").glob("hq_*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        items = next(v for v in obj.values() if isinstance(v, list)) if isinstance(obj, dict) else obj
        total += len(items)
    assert total == 120, f"expected 120 historical Q&A pairs, found {total}"


def test_firm_name_is_consistent() -> None:
    """One firm identity across the corpus, or retrieval returns a stranger's answers."""
    stale = []
    for folder in INGESTIBLE + ["incoming", "eval"]:
        for path in (DATA / folder).rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".csv", ".yaml"}:
                if "sealed" in path.parts:
                    continue
                if "Digital Trends" in path.read_text(encoding="utf-8", errors="ignore"):
                    stale.append(str(path.relative_to(DATA)))
    assert not stale, f"old firm name still present in: {stale}"
