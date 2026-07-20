"""Phase 0 acceptance test.

Gate: `python -c "import src"` clean; the repo tree matches plan section 5;
`pytest` collects. The Ollama liveness check is a separate opt-in test because
CLAUDE.md forbids an acceptance test that cannot run offline — but Phase 0 does
require a reachable model, so it is reported as a skip, not a silent pass.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

PACKAGES = [
    "src",
    "src.llm",
    "src.models",
    "src.ingestion",
    "src.agents",
    "src.writers",
    "src.assurance",
    "src.workflow",
    "src.utils",
]

MODULES = [
    "src/llm/provider.py",
    "src/models/schemas.py",
    "src/models/db.py",
    "src/ingestion/ingest.py",
    "src/ingestion/calibrate.py",
    "src/agents/structurer.py",
    "src/agents/requirements.py",
    "src/agents/buyer_intel.py",
    "src/agents/qualifier.py",
    "src/agents/win_themes.py",
    "src/agents/architect.py",
    "src/agents/proofs.py",
    "src/agents/retriever.py",
    "src/agents/generator.py",
    "src/writers/narrative.py",
    "src/writers/structured.py",
    "src/writers/quant_modeler.py",
    "src/writers/visual_generator.py",
    "src/writers/boilerplate.py",
    "src/assurance/consistency.py",
    "src/assurance/compliance.py",
    "src/assurance/grounding.py",
    "src/assurance/polish.py",
    "src/workflow/router.py",
    "src/workflow/tracker.py",
    "src/workflow/assembler.py",
    "src/orchestrator.py",
    "src/utils/docparse.py",
    "src/utils/provenance.py",
    "src/utils/metrics.py",
    "app/dashboard.py",
]

DATA_DIRS = [
    "data/incoming",
    "data/knowledge_base",
    "data/historical_rfps",
    "data/proof_library",
    "data/templates",
    "data/eval",
    "db",
]


@pytest.mark.parametrize("pkg", PACKAGES)
def test_package_imports(pkg: str) -> None:
    assert importlib.import_module(pkg) is not None


@pytest.mark.parametrize("mod", MODULES)
def test_module_exists_with_contract_docstring(mod: str) -> None:
    path = ROOT / mod
    assert path.is_file(), f"missing module {mod}"
    text = path.read_text(encoding="utf-8").lstrip()
    assert text.startswith('"""'), f"{mod} has no contract docstring"
    assert len(text) > 40, f"{mod} docstring does not state a contract"


@pytest.mark.parametrize("d", DATA_DIRS)
def test_data_dirs_exist(d: str) -> None:
    assert (ROOT / d).is_dir(), f"missing directory {d}"


def test_root_files_exist() -> None:
    for f in ["CLAUDE.md", "README.md", "requirements.txt", ".env.example", "config.py"]:
        assert (ROOT / f).is_file(), f"missing {f}"


def test_settings_load_with_defaults() -> None:
    """Settings must resolve with no .env present."""
    from config import get_settings

    s = get_settings()
    assert s.sqlite_path.name == "rfp_copilot.db"
    assert s.embedding_model.startswith("BAAI/"), "embeddings stay local per CLAUDE.md"


def test_provider_chain_parses_and_validates() -> None:
    from config import KNOWN_PROVIDERS, Settings

    s = Settings(llm_provider_chain="groq, gemini ,huggingface")
    assert s.provider_chain == ["groq", "gemini", "huggingface"]
    assert all(p in KNOWN_PROVIDERS for p in s.provider_chain)

    with pytest.raises(ValueError, match="unknown provider"):
        Settings(llm_provider_chain="groq,openai").provider_chain
    with pytest.raises(ValueError, match="empty"):
        Settings(llm_provider_chain="  ").provider_chain


def test_ollama_needs_no_key_but_cloud_does() -> None:
    """Ollama is the offline degradation path and must stay usable with no credentials."""
    from config import Settings

    s = Settings(groq_api_key="", llm_provider_chain="groq,ollama")
    assert s.provider("ollama").configured is True
    assert s.provider("groq").configured is False
    assert [p.name for p in s.available_providers()] == ["ollama"]


def test_provider_repr_never_leaks_the_key() -> None:
    from config import Settings

    s = Settings(groq_api_key="gsk_supersecret_value")
    assert "supersecret" not in repr(s.provider("groq"))


def test_tier_selects_distinct_models() -> None:
    from config import Settings

    p = Settings().provider("groq")
    assert p.model_for("cheap") != p.model_for("strong")


def test_no_llm_calls_outside_provider() -> None:
    """CLAUDE.md: no module may reach Ollama except src/llm/provider.py."""
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if path.as_posix().endswith("src/llm/provider.py"):
            continue
        if "ollama" in path.read_text(encoding="utf-8").lower():
            offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f"Ollama referenced outside provider.py: {offenders}"


@pytest.mark.skipif(
    os.environ.get("RFP_SKIP_OLLAMA") == "1", reason="RFP_SKIP_OLLAMA=1"
)
def test_offline_fallback_model_available() -> None:
    """Ollama is the offline degradation path, not the primary. Skips loudly if absent."""
    httpx = pytest.importorskip("httpx")
    from config import get_settings

    s = get_settings()
    try:
        r = httpx.get(f"{s.ollama_base_url}/api/tags", timeout=5)
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Ollama not reachable at {s.ollama_base_url}: {exc}")
    assert r.status_code == 200
    names = [m["name"] for m in r.json().get("models", [])]
    want = s.ollama_model_cheap
    assert any(n.startswith(want.split(":")[0] + ":" + want.split(":")[1][:2]) for n in names), (
        f"offline fallback model {want} not pulled; found {names}"
    )
