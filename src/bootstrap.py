"""Deployment bootstrap.

The search indices (Chroma, BM25) and the calibration thresholds are generated
artefacts, gitignored, so a fresh clone or a fresh cloud deploy has none of them. This
builds them if they are missing, and does nothing if they are already present.

Idempotent and safe to call at every app start. It is the one thing that lets the web
app come up on a platform where only the API keys are configured -- everything else
(the corpus, the code) is in the repo, and this turns the corpus into the indices the
pipeline needs.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def indices_present(settings=None) -> bool:
    if settings is None:
        from config import get_settings

        settings = get_settings()
    return (
        settings.chroma_path.exists()
        and settings.bm25_index_path.is_file()
        and settings.thresholds_path.is_file()
    )


def ensure_indices(settings=None, progress=None) -> bool:
    """Build the indices and calibration if absent. Returns True if it built anything.

    `progress` is an optional callable(str) for surfacing status in a UI.
    """
    if settings is None:
        from config import get_settings

        settings = get_settings()

    if indices_present(settings):
        return False

    say = progress or (lambda _m: None)

    say("Building the search index (first run only)…")
    log.info("indices missing; running ingestion")
    from src.ingestion.ingest import Ingestor

    Ingestor(settings).run()

    say("Calibrating retrieval thresholds…")
    log.info("running calibration")
    from src.ingestion.calibrate import Calibrator

    Calibrator(settings).run()

    say("Index ready.")
    return True
