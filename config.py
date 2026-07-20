"""Central configuration.

Contract: the single source of truth for paths, model names and provider settings.
Nothing else in the codebase reads os.environ directly.

Retrieval thresholds are deliberately NOT defined here. They are calibrated at ingest
(Phase 2) and read from `config/thresholds.json` via `load_thresholds()`. Hardcoding
them is a violation of CLAUDE.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    """Environment-backed settings. See .env.example for the full template."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider ---
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    llm_model_cheap: str = "qwen2.5:7b-instruct"
    llm_model_strong: str = "qwen2.5:7b-instruct"
    llm_model_fallback: str = "llama3.1:8b-instruct"
    llm_timeout_seconds: int = 180
    llm_max_json_retries: int = 1

    # --- Local models ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Optional cloud accelerators. Never required by any acceptance test. ---
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # --- Paths, relative to repo root ---
    data_dir: Path = Path("data")
    db_dir: Path = Path("db")
    output_dir: Path = Path("output")

    # --- Derived absolute paths ---
    @property
    def data_path(self) -> Path:
        return ROOT / self.data_dir

    @property
    def db_path(self) -> Path:
        return ROOT / self.db_dir

    @property
    def output_path(self) -> Path:
        return ROOT / self.output_dir

    @property
    def sqlite_path(self) -> Path:
        return self.db_path / "rfp_copilot.db"

    @property
    def chroma_path(self) -> Path:
        return self.db_path / "chroma"

    @property
    def bm25_index_path(self) -> Path:
        return self.db_path / "bm25_index.pkl"

    @property
    def thresholds_path(self) -> Path:
        return ROOT / "config" / "thresholds.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()


settings = get_settings()
