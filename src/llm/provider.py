"""LLM provider wrapper — Phase 2.

Contract:
    generate(prompt, tier, schema=None) -> LLMResponse
    generate_many(prompts, tier, schema=None) -> list[LLMResponse]
    embed(texts) -> list[list[float]]
    rerank(query, docs) -> list[tuple[int, float]]

No other module in the codebase may call a model. Agents never learn which backend
served their call.

Provider policy (see CLAUDE.md):
- Generation runs on pooled free-tier cloud with failover: groq -> gemini -> huggingface.
  A rate limit or provider fault falls through to the next backend rather than failing
  the run. Ollama remains supported as the offline degradation path.
- Embeddings and reranking are LOCAL and are never routed to a provider. Cloud embedding
  would exhaust free-tier rate limits during a single ingest pass.

Every call is throttled client-side before the remote can reject it, and every call
returns which provider and model served it so provider mix can be reported.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from config import ProviderConfig, get_settings

log = logging.getLogger(__name__)

Tier = Literal["cheap", "strong"]


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Base for provider failures."""


class RateLimited(LLMError):
    """The backend refused the call for quota reasons. Failover should try the next."""


class ProviderUnavailable(LLMError):
    """The backend is unreachable, misconfigured, or the model does not exist."""


class AllProvidersFailed(LLMError):
    """Every backend in the chain failed. Carries the per-provider reasons."""

    def __init__(self, reasons: dict[str, str]) -> None:
        self.reasons = reasons
        detail = "; ".join(f"{k}: {v}" for k, v in reasons.items())
        super().__init__(f"all providers failed -> {detail}")


# --------------------------------------------------------------------------------------
# Response
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class LLMResponse:
    """One completed generation, with the provenance the runs table needs."""

    text: str
    provider: str
    model: str
    tier: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    cached: bool = False
    attempts: list[str] = field(default_factory=list)
    parsed: Any = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# --------------------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------------------


class TokenBucket:
    """Sliding-window limiter. Throttles before the remote does.

    A free tier that returns 429 costs a round trip and a failover; waiting 200ms costs
    200ms. On a live demo the second is always the better trade.
    """

    def __init__(self, rpm: int, now=time.monotonic, sleep=time.sleep) -> None:
        self.rpm = max(1, rpm)
        self._times: deque[float] = deque()
        self._lock = threading.Lock()
        # Injectable so tests can drive a fake clock instead of waiting a real minute.
        self._now = now
        self._sleep = sleep

    def acquire(self) -> float:
        """Block until a request slot is free. Returns seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = self._now()
                while self._times and now - self._times[0] >= 60.0:
                    self._times.popleft()
                if len(self._times) < self.rpm:
                    self._times.append(now)
                    return waited
                sleep_for = 60.0 - (now - self._times[0]) + 0.01
            self._sleep(sleep_for)
            waited += sleep_for


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------

#: 402 belongs here rather than with the outages: HuggingFace returns Payment Required
#: when an account's free inference credits run out, which is a quota condition. Treating
#: it as a rate limit means the chain moves on to the next provider instead of retrying.
_RATE_LIMIT_MARKERS = ("429", "402", "rate limit", "resource_exhausted", "quota",
                       "too many requests", "payment required", "credits")
_UNAVAILABLE_MARKERS = ("503", "500", "502", "504", "unavailable", "overloaded",
                        "not_found", "404", "disconnected", "high demand")


def _classify(exc: Exception) -> LLMError:
    """Map a backend-specific exception onto a failover decision."""
    msg = f"{type(exc).__name__}: {exc}"
    low = msg.lower()
    if any(m in low for m in _RATE_LIMIT_MARKERS):
        return RateLimited(msg)
    if any(m in low for m in _UNAVAILABLE_MARKERS):
        return ProviderUnavailable(msg)
    return ProviderUnavailable(msg)


class _Backend:
    """One provider. Subclasses translate a single SDK into the common shape."""

    name = "base"

    def __init__(self, cfg: ProviderConfig, timeout: int) -> None:
        self.cfg = cfg
        self.timeout = timeout
        self.bucket = TokenBucket(cfg.rpm)

    def complete(self, prompt: str, system: str | None, model: str,
                 json_mode: bool) -> tuple[str, int, int]:
        raise NotImplementedError


class GroqBackend(_Backend):
    name = "groq"

    def complete(self, prompt, system, model, json_mode):
        from groq import Groq

        client = Groq(api_key=self.cfg.api_key, timeout=float(self.timeout))
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat.completions.create(**kwargs)
        usage = r.usage
        return (
            r.choices[0].message.content or "",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )


class GeminiBackend(_Backend):
    name = "gemini"

    def complete(self, prompt, system, model, json_mode):
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.cfg.api_key)
        cfg: dict[str, Any] = {}
        if system:
            cfg["system_instruction"] = system
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        r = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg) if cfg else None,
        )
        um = getattr(r, "usage_metadata", None)
        return (
            r.text or "",
            getattr(um, "prompt_token_count", 0) or 0,
            getattr(um, "candidates_token_count", 0) or 0,
        )


class HuggingFaceBackend(_Backend):
    name = "huggingface"

    def complete(self, prompt, system, model, json_mode):
        from huggingface_hub import InferenceClient

        client = InferenceClient(api_key=self.cfg.api_key, timeout=float(self.timeout))
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 4096}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = client.chat_completion(**kwargs)
        usage = getattr(r, "usage", None)
        return (
            r.choices[0].message.content or "",
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )


class OllamaBackend(_Backend):
    """Offline degradation path. Slow but requires no key and no network."""

    name = "ollama"

    def complete(self, prompt, system, model, json_mode):
        import httpx

        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        r = httpx.post(
            f"{self.cfg.base_url}/api/generate", json=payload, timeout=float(self.timeout)
        )
        r.raise_for_status()
        d = r.json()
        return d.get("response", ""), d.get("prompt_eval_count", 0), d.get("eval_count", 0)


_BACKENDS: dict[str, type[_Backend]] = {
    "groq": GroqBackend,
    "gemini": GeminiBackend,
    "huggingface": HuggingFaceBackend,
    "ollama": OllamaBackend,
}


# --------------------------------------------------------------------------------------
# JSON handling
# --------------------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating fences and surrounding prose."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced object or array.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no parseable JSON in response: {text[:200]!r}")


# --------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------


class ResponseCache:
    """Content-hash cache on disk.

    The key deliberately excludes the provider, so a cached result is reused no matter
    which backend originally served it. `LLMResponse.cached` records the distinction so
    the UI can show it rather than passing a cache hit off as a live call.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(prompt: str, system: str | None, tier: str, json_mode: bool) -> str:
        h = hashlib.sha256()
        for part in (prompt, system or "", tier, str(json_mode)):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def get(self, key: str) -> LLMResponse | None:
        f = self.path / f"{key}.json"
        if not f.is_file():
            return None
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return LLMResponse(
            text=d["text"], provider=d["provider"], model=d["model"], tier=d["tier"],
            prompt_tokens=d.get("prompt_tokens", 0),
            completion_tokens=d.get("completion_tokens", 0),
            latency_s=d.get("latency_s", 0.0), cached=True,
        )

    def put(self, key: str, resp: LLMResponse) -> None:
        f = self.path / f"{key}.json"
        try:
            f.write_text(json.dumps({
                "text": resp.text, "provider": resp.provider, "model": resp.model,
                "tier": resp.tier, "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens, "latency_s": resp.latency_s,
            }), encoding="utf-8")
        except OSError as exc:  # a cache miss is survivable; a crash is not
            log.warning("cache write failed for %s: %s", key[:8], exc)


# --------------------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------------------


class LLMProvider:
    """The single gateway to every model call in the system."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self._backends: dict[str, _Backend] = {}
        self._cache = ResponseCache(self.settings.cache_path)
        self._embedder = None
        self._reranker = None
        self._lock = threading.Lock()
        #: Guards construction of the local models. Separate from _inference_lock so a
        #: long encode does not block another thread merely checking whether it loaded.
        self._model_lock = threading.Lock()
        #: Serialises calls into the local torch models, which share mutable state.
        self._inference_lock = threading.Lock()
        #: Per-call telemetry, drained into the runs table by the orchestrator.
        self.call_log: list[dict[str, Any]] = []

        self._chain = [p for p in self.settings.available_providers()]
        if not self._chain:
            raise ProviderUnavailable(
                "no provider is configured. Put a key in .env (GROQ_API_KEY, "
                "GEMINI_API_KEY or HUGGINGFACE_API_KEY), or set "
                "LLM_PROVIDER_CHAIN=ollama for the offline path."
            )

    # --- backend access ------------------------------------------------------------

    def _backend(self, cfg: ProviderConfig) -> _Backend:
        with self._lock:
            if cfg.name not in self._backends:
                self._backends[cfg.name] = _BACKENDS[cfg.name](
                    cfg, self.settings.llm_timeout_seconds
                )
            return self._backends[cfg.name]

    @property
    def chain_names(self) -> list[str]:
        return [c.name for c in self._chain]

    # --- generation ----------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        tier: Tier = "cheap",
        schema: type[BaseModel] | None = None,
        *,
        system: str | None = None,
        use_cache: bool | None = None,
    ) -> LLMResponse:
        """Generate once, failing over across the provider chain.

        If `schema` is given the call runs in JSON mode and the response is validated
        against the pydantic model. An invalid response is retried once with the
        validation error fed back into the prompt, per the plan's reparse rule.
        """
        json_mode = schema is not None
        cache_on = self.settings.llm_cache_enabled if use_cache is None else use_cache
        ckey = ResponseCache.key(prompt, system, tier, json_mode)

        if cache_on:
            hit = self._cache.get(ckey)
            if hit is not None:
                if schema is not None:
                    try:
                        hit.parsed = schema.model_validate(extract_json(hit.text))
                    except (ValueError, ValidationError):
                        hit = None  # poisoned entry; regenerate
                if hit is not None:
                    self._record(hit)
                    return hit

        attempt_prompt = prompt
        last_error: Exception | None = None

        for round_index in range(self.settings.llm_max_json_retries + 1):
            resp = self._call_chain(attempt_prompt, system, tier, json_mode)
            if schema is None:
                if cache_on:
                    self._cache.put(ckey, resp)
                self._record(resp)
                return resp
            try:
                resp.parsed = schema.model_validate(extract_json(resp.text))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                log.warning(
                    "JSON validation failed on round %d (%s): %s",
                    round_index, resp.provider, str(exc)[:200],
                )
                attempt_prompt = (
                    f"{prompt}\n\n"
                    f"Your previous response could not be parsed into the required "
                    f"schema. Error:\n{str(exc)[:800]}\n\n"
                    f"Return ONLY valid JSON matching the schema. No prose, no code fences."
                )
                continue
            if cache_on:
                self._cache.put(ckey, resp)
            self._record(resp)
            return resp

        raise LLMError(f"schema validation failed after reparse: {last_error}")

    def generate_many(
        self,
        prompts: list[str],
        tier: Tier = "cheap",
        schema: type[BaseModel] | None = None,
        *,
        system: str | None = None,
    ) -> list[LLMResponse]:
        """Generate concurrently, preserving input order.

        Concurrency is what makes a live end-to-end demo viable; the token buckets keep
        it from tripping a rate limit.
        """
        if not prompts:
            return []
        workers = min(self.settings.llm_max_concurrency, len(prompts))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(
                pool.map(lambda p: self.generate(p, tier, schema, system=system), prompts)
            )

    def _call_chain(self, prompt: str, system: str | None, tier: str,
                    json_mode: bool) -> LLMResponse:
        """Try each configured provider in order until one answers."""
        reasons: dict[str, str] = {}
        attempts: list[str] = []

        for cfg in self._chain:
            backend = self._backend(cfg)
            model = cfg.model_for(tier)
            for attempt in range(self.settings.llm_max_attempts_per_provider):
                backend.bucket.acquire()
                t0 = time.time()
                try:
                    text, ptok, ctok = backend.complete(prompt, system, model, json_mode)
                except Exception as exc:  # noqa: BLE001 - normalized by _classify
                    err = _classify(exc)
                    reasons[cfg.name] = str(err)[:300]
                    attempts.append(f"{cfg.name}:{type(err).__name__}")
                    log.warning("%s failed (attempt %d): %s", cfg.name, attempt + 1,
                                str(err)[:200])
                    if isinstance(err, RateLimited) and attempt == 0:
                        time.sleep(2.0)  # one short backoff before moving on
                        continue
                    break
                attempts.append(cfg.name)
                return LLMResponse(
                    text=text, provider=cfg.name, model=model, tier=tier,
                    prompt_tokens=ptok, completion_tokens=ctok,
                    latency_s=time.time() - t0, attempts=attempts,
                )
        raise AllProvidersFailed(reasons)

    def _record(self, resp: LLMResponse) -> None:
        self.call_log.append({
            "provider": resp.provider, "model": resp.model, "tier": resp.tier,
            "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens,
            "latency_s": round(resp.latency_s, 3), "cached": resp.cached,
        })

    def usage_summary(self) -> dict[str, Any]:
        """Provider mix and token totals for the runs table and the automation report."""
        mix: dict[str, int] = {}
        for c in self.call_log:
            mix[c["provider"]] = mix.get(c["provider"], 0) + 1
        return {
            "calls": len(self.call_log),
            "cached": sum(1 for c in self.call_log if c["cached"]),
            "provider_mix": mix,
            "prompt_tokens": sum(c["prompt_tokens"] for c in self.call_log),
            "completion_tokens": sum(c["completion_tokens"] for c in self.call_log),
            "total_latency_s": round(sum(c["latency_s"] for c in self.call_log), 2),
        }

    # --- local models: never routed to a provider ----------------------------------

    # Loading a sentence-transformers model is not thread safe, and neither is calling
    # into one while another thread is still constructing it. Sections retrieve
    # concurrently, so six threads racing to build the CrossEncoder crashed the
    # interpreter outright rather than raising. Construction is locked, and inference is
    # serialised behind the same lock because the underlying torch modules are shared.
    def _load_model(self, attribute: str, factory) -> object:
        existing = getattr(self, attribute)
        if existing is not None:
            return existing
        with self._model_lock:
            if getattr(self, attribute) is None:
                setattr(self, attribute, factory())
            return getattr(self, attribute)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed locally with bge-small. See CLAUDE.md for why this is not cloud."""
        if not texts:
            return []

        def build():
            from sentence_transformers import SentenceTransformer

            log.info("loading local embedder %s", self.settings.embedding_model)
            return SentenceTransformer(self.settings.embedding_model)

        model = self._load_model("_embedder", build)
        with self._inference_lock:
            return model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            ).tolist()

    def rerank(self, query: str, docs: list[str]) -> list[tuple[int, float]]:
        """Cross-encoder rerank. Returns (original_index, score), best first."""
        if not docs:
            return []

        def build():
            from sentence_transformers import CrossEncoder

            log.info("loading local reranker %s", self.settings.reranker_model)
            return CrossEncoder(self.settings.reranker_model)

        model = self._load_model("_reranker", build)
        with self._inference_lock:
            scores = model.predict([(query, d) for d in docs])
        return sorted(enumerate(float(s) for s in scores), key=lambda t: t[1],
                      reverse=True)


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Process-wide provider singleton."""
    global _provider
    if _provider is None:
        _provider = LLMProvider()
    return _provider
