"""Phase 2b acceptance test — ingestion and calibration.

Gate: indices built, calibration report written, a test query returns sensible
neighbours. Chunking tests run offline against the real corpus; anything that embeds is
marked `slow`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import get_settings
from src.ingestion import calibrate as C
from src.ingestion import ingest as I
from src.models.schemas import CalibrationThresholds, ChunkKind, ReuseDecision

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def chunks():
    return I.collect_chunks(DATA)


# --------------------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------------------


def test_all_four_sources_are_chunked(chunks) -> None:
    kinds = {c.kind for c in chunks}
    assert kinds == {
        ChunkKind.KNOWLEDGE_BASE, ChunkKind.HISTORICAL_QA,
        ChunkKind.PROOF_POINT, ChunkKind.TEMPLATE,
    }


def test_chunk_ids_are_unique(chunks) -> None:
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_every_historical_pair_is_one_chunk(chunks) -> None:
    """The Q&A pair is the unit a human reuses; splitting it would break REUSE."""
    qa = [c for c in chunks if c.kind is ChunkKind.HISTORICAL_QA]
    assert len(qa) == 120
    assert all(c.text.startswith("Q: ") and "\n\nA: " in c.text for c in qa)


def test_proof_claim_and_evidence_stay_together(chunks) -> None:
    """A claim separated from its evidence could be retrieved unevidenced."""
    proofs = [c for c in chunks if c.kind is ChunkKind.PROOF_POINT]
    assert len(proofs) == 20
    assert all("Claim:" in c.text and "Evidence:" in c.text for c in proofs)


def test_no_sliver_chunks(chunks) -> None:
    """A bare heading embeds to noise and competes with real content at retrieval."""
    slivers = [(c.id, len(c.text)) for c in chunks if len(c.text.strip()) < 150]
    assert not slivers, f"chunks too small to carry meaning: {slivers}"


def test_split_chunks_respect_the_size_ceiling(chunks) -> None:
    """Applies to sources that are split. Templates are exempt by design."""
    splittable = [c for c in chunks if c.kind is not ChunkKind.TEMPLATE]
    oversized = [(c.id, len(c.text)) for c in splittable if len(c.text) > I.MAX_CHARS + 50]
    assert not oversized, f"chunks exceed MAX_CHARS: {oversized}"


def test_templates_are_kept_whole(chunks) -> None:
    """Boilerplate is filled as a unit; a half template is not fillable."""
    tmpl = [c for c in chunks if c.kind is ChunkKind.TEMPLATE]
    assert len(tmpl) == 5
    assert all("#" not in c.id for c in tmpl), "templates must not be split"


def test_oversized_templates_are_a_known_truncation_risk(chunks) -> None:
    """bge-small encodes 512 tokens (~2000 chars); longer text is silently truncated.

    Templates exceed that deliberately, so their embeddings represent only the opening.
    That is acceptable because boilerplate is selected by section type in Phase 7, not by
    dense similarity. This test records the fact so the behaviour cannot change silently.
    """
    truncated = [c.id for c in chunks
                 if c.kind is ChunkKind.TEMPLATE and len(c.text) > 2000]
    assert set(truncated) <= {
        "TMPL-about_us", "TMPL-assumptions", "TMPL-compliance_matrix",
        "TMPL-cover_page", "TMPL-exclusions",
    }, f"an unexpected chunk is being truncated at embed time: {truncated}"

    non_template = [c.id for c in chunks
                    if c.kind is not ChunkKind.TEMPLATE and len(c.text) > 2000]
    assert not non_template, (
        f"retrievable content is being truncated at embed time: {non_template}"
    )


def test_source_ids_match_the_labelled_eval_references(chunks) -> None:
    """retrieval_pairs.json refers to HQ-014 / KB-003. Those ids must exist."""
    have = {c.source_id for c in chunks}
    pairs = json.loads(
        (DATA / "eval" / "retrieval_pairs.json").read_text(encoding="utf-8")
    )["retrieval_pairs"]
    referenced = {i for p in pairs for i in p["relevant_ids"]}
    missing = sorted(referenced - have)
    assert not missing, f"eval set references chunks that do not exist: {missing}"


def test_knowledge_base_chunks_carry_the_document_id(chunks) -> None:
    kb = [c for c in chunks if c.kind is ChunkKind.KNOWLEDGE_BASE]
    assert all(c.source_id.startswith("KB-") for c in kb)
    assert all(c.id.startswith(c.source_id + "#") for c in kb)


def test_tokenizer_preserves_regulatory_terms() -> None:
    """BM25 exists for exact terms. GDPR/SOC2/PSD2 must survive tokenization."""
    toks = I.tokenize("We comply with GDPR, SOC 2 Type II, PSD2 and ISO 27001.")
    for term in ["gdpr", "soc", "psd2", "iso", "27001"]:
        assert term in toks, f"{term} lost in tokenization: {toks}"


def test_split_long_overlaps_and_bounds() -> None:
    text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(12))
    parts = I._split_long(text, max_chars=800, overlap=100)
    assert len(parts) > 1
    assert all(len(p) <= 900 for p in parts)


# --------------------------------------------------------------------------------------
# The ingestion boundary — the guard that protects the sealed test set
# --------------------------------------------------------------------------------------


def test_ingestion_never_reads_forbidden_directories(chunks) -> None:
    """CLAUDE.md: eval, incoming and archive_xcd are out of bounds."""
    refs = {c.source_ref for c in chunks}
    for ref in refs:
        for forbidden in I.FORBIDDEN_DIRS:
            assert forbidden not in ref, f"chunk sourced from {forbidden}: {ref}"


def test_no_sealed_content_reached_the_corpus(chunks) -> None:
    """A sealed RFP in the index would invalidate every metric reported afterwards."""
    for c in chunks:
        assert "RFP-D" not in c.source_ref and "RFP-E" not in c.source_ref
        assert "sealed" not in c.source_ref
        assert "golden" not in c.source_ref


def test_incoming_rfps_are_not_ingested(chunks) -> None:
    """incoming/ holds RFPs to answer, not knowledge to answer them with."""
    assert not [c for c in chunks if c.source_ref.startswith("RFP-")]


def test_ingestible_and_forbidden_sets_are_disjoint() -> None:
    assert not set(I.INGESTIBLE_DIRS) & set(I.FORBIDDEN_DIRS)


# --------------------------------------------------------------------------------------
# Calibration maths, without touching a model
# --------------------------------------------------------------------------------------


def test_percentile_interpolates() -> None:
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert C._pct(vals, 0) == 0.0
    assert C._pct(vals, 100) == 4.0
    assert C._pct(vals, 50) == 2.0


def test_percentile_handles_degenerate_input() -> None:
    assert C._pct([], 50) == 0.0
    assert C._pct([0.7], 99) == 0.7


def test_thresholds_reject_inverted_bands() -> None:
    with pytest.raises(ValueError, match="must exceed"):
        CalibrationThresholds(
            version="v", method="m", embedding_model="e",
            reuse_min=0.5, adapt_min=0.8, n_pairs=10,
        )


def test_decide_maps_scores_onto_bands() -> None:
    t = CalibrationThresholds(
        version="v", method="m", embedding_model="e",
        reuse_min=0.80, adapt_min=0.74, n_pairs=100,
    )
    assert t.decide(0.95) is ReuseDecision.REUSE
    assert t.decide(0.80) is ReuseDecision.REUSE
    assert t.decide(0.79) is ReuseDecision.ADAPT
    assert t.decide(0.74) is ReuseDecision.ADAPT
    assert t.decide(0.73) is ReuseDecision.SYNTHESIZE


def test_stakeholder_is_never_score_derived() -> None:
    """It comes from the Compliance/Legal/GAP guardrail and must be unreachable here."""
    t = CalibrationThresholds(
        version="v", method="m", embedding_model="e",
        reuse_min=0.80, adapt_min=0.74, n_pairs=100,
    )
    for score in [x / 100 for x in range(-100, 101)]:
        assert t.decide(score) is not ReuseDecision.STAKEHOLDER


def test_derive_refuses_too_small_a_background() -> None:
    with pytest.raises(ValueError, match="too few"):
        C.Calibrator(provider=object())._derive([0.5] * 10)


# --------------------------------------------------------------------------------------
# Artefacts produced by a real run
# --------------------------------------------------------------------------------------


def test_thresholds_file_exists_and_is_ordered() -> None:
    t = C.load_thresholds()
    assert t.reuse_min > t.adapt_min
    assert 0.0 < t.adapt_min < 1.0
    assert t.embedding_model == get_settings().embedding_model
    assert t.n_pairs > 1000, "background distribution should span the whole corpus"


def test_calibration_report_was_written() -> None:
    report = (get_settings().output_path / "calibration_report.md").read_text(
        encoding="utf-8"
    )
    assert "Derived thresholds" in report
    assert "STAKEHOLDER" in report
    assert "Background distribution" in report


def test_bm25_index_round_trips() -> None:
    bm25, loaded = I.load_bm25()
    assert len(loaded) > 100
    scores = bm25.get_scores(I.tokenize("GDPR data protection compliance"))
    assert len(scores) == len(loaded)
    assert max(scores) > 0, "a corpus term must score above zero"


@pytest.mark.slow
def test_dense_retrieval_returns_sensible_neighbours() -> None:
    """Phase 2 gate: a test query returns plausible neighbours."""
    import chromadb

    from src.llm.provider import get_provider

    s = get_settings()
    client = chromadb.PersistentClient(path=str(s.chroma_path))
    collection = client.get_collection(I.COLLECTION)
    qv = get_provider().embed(["What are your data protection and GDPR commitments?"])[0]
    res = collection.query(query_embeddings=[qv], n_results=5)

    docs = res["documents"][0]
    assert len(docs) == 5
    blob = " ".join(docs).lower()
    assert any(term in blob for term in ["data", "protection", "privacy", "gdpr", "dpdp"]), (
        f"neighbours look unrelated: {[d[:60] for d in docs]}"
    )
