"""Central configuration.

Contract: the single source of truth for paths, model names and provider settings.
Nothing else in the codebase reads os.environ directly.

Two deliberate absences:
- Retrieval thresholds. They are calibrated at ingest (Phase 2) and read from
  `config/thresholds.json` via the calibration module. Hardcoding them violates CLAUDE.md.
- Any provider selection logic. This module describes the providers; `src/llm/provider.py`
  decides which one serves a given call.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).parent.resolve()

#: Providers in the order they may appear in a failover chain.
KNOWN_PROVIDERS = ("groq", "gemini", "huggingface", "ollama")


class ProviderConfig:
    """Resolved settings for one provider. Built by Settings.provider(); not a contract."""

    def __init__(
        self,
        name: str,
        api_key: str,
        model_cheap: str,
        model_strong: str,
        rpm: int,
        base_url: str | None = None,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.model_cheap = model_cheap
        self.model_strong = model_strong
        self.rpm = rpm
        self.base_url = base_url

    def model_for(self, tier: str) -> str:
        return self.model_strong if tier == "strong" else self.model_cheap

    @property
    def configured(self) -> bool:
        """Ollama needs no key; every cloud provider does."""
        return self.name == "ollama" or bool(self.api_key)

    def __repr__(self) -> str:  # never leak the key
        return f"ProviderConfig({self.name!r}, configured={self.configured})"


class Settings(BaseSettings):
    """Environment-backed settings. See .env.example for the full template."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Provider routing ---
    llm_provider_chain: str = "groq,gemini,huggingface"

    # --- Keys ---
    groq_api_key: str = ""
    gemini_api_key: str = ""
    huggingface_api_key: str = ""

    # --- Models per tier ---
    groq_model_cheap: str = "llama-3.1-8b-instant"
    groq_model_strong: str = "llama-3.3-70b-versatile"
    gemini_model_cheap: str = "gemini-2.5-flash-lite"
    gemini_model_strong: str = "gemini-2.5-flash"
    huggingface_model_cheap: str = "meta-llama/Llama-3.1-8B-Instruct"
    huggingface_model_strong: str = "meta-llama/Llama-3.3-70B-Instruct"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_cheap: str = "qwen2.5:3b-instruct"
    ollama_model_strong: str = "qwen2.5:3b-instruct"

    # --- Rate limiting and resilience ---
    groq_rpm: int = 28
    gemini_rpm: int = 14
    huggingface_rpm: int = 10
    ollama_rpm: int = 1000
    llm_timeout_seconds: int = 90
    llm_max_json_retries: int = 1
    llm_max_attempts_per_provider: int = 2
    llm_max_concurrency: int = Field(default=4, ge=1)
    llm_cache_enabled: bool = True

    # --- Local models (never cloud — see CLAUDE.md provider policy) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Paths, relative to repo root ---
    data_dir: Path = Path("data")
    db_dir: Path = Path("db")
    output_dir: Path = Path("output")

    # ---------------------------------------------------------------------------------
    # Provider resolution
    # ---------------------------------------------------------------------------------

    def provider(self, name: str) -> ProviderConfig:
        """Resolve one provider's settings by name."""
        if name not in KNOWN_PROVIDERS:
            raise ValueError(f"unknown provider {name!r}; expected one of {KNOWN_PROVIDERS}")
        return ProviderConfig(
            name=name,
            api_key=getattr(self, f"{name}_api_key", ""),
            model_cheap=getattr(self, f"{name}_model_cheap"),
            model_strong=getattr(self, f"{name}_model_strong"),
            rpm=getattr(self, f"{name}_rpm"),
            base_url=self.ollama_base_url if name == "ollama" else None,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def provider_chain(self) -> list[str]:
        """The failover order, validated. Order matters: first is preferred."""
        names = [p.strip().lower() for p in self.llm_provider_chain.split(",") if p.strip()]
        unknown = [n for n in names if n not in KNOWN_PROVIDERS]
        if unknown:
            raise ValueError(
                f"unknown provider(s) in LLM_PROVIDER_CHAIN: {unknown}; "
                f"expected from {KNOWN_PROVIDERS}"
            )
        if not names:
            raise ValueError("LLM_PROVIDER_CHAIN is empty")
        return names

    def available_providers(self) -> list[ProviderConfig]:
        """Chain members that actually have credentials. Empty means nothing can run."""
        return [p for p in (self.provider(n) for n in self.provider_chain) if p.configured]

    # ---------------------------------------------------------------------------------
    # Derived absolute paths
    # ---------------------------------------------------------------------------------

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
    def cache_path(self) -> Path:
        return self.db_path / "llm_cache"

    @property
    def thresholds_path(self) -> Path:
        return ROOT / "config" / "thresholds.json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()


settings = get_settings()
