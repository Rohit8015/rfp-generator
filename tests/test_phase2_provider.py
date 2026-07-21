"""Phase 2 acceptance test — provider wrapper.

Offline tests use fake backends so failover, throttling, caching and JSON reparse are
verified deterministically. Live tests are marked `live` and skipped when a key is
absent, so the suite stays green on a fresh clone with no credentials.

Run everything:        pytest
Skip the network:      pytest -m "not live"
Only the live checks:  pytest -m live
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from config import Settings
from src.llm import provider as P


class Answer(BaseModel):
    verdict: str
    score: int


# --------------------------------------------------------------------------------------
# Fake backends
# --------------------------------------------------------------------------------------


class FakeBackend(P._Backend):
    """Scripted backend. Each entry is either an Exception to raise or a text to return."""

    name = "fake"

    def __init__(self, cfg, timeout, script):
        super().__init__(cfg, timeout)
        self.script = list(script)
        self.calls = 0

    def complete(self, prompt, system, model, json_mode, max_tokens=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else "default"
        if isinstance(item, Exception):
            raise item
        return item, 11, 22


def build(monkeypatch, scripts: dict[str, list], chain: str, **overrides):
    """Wire a provider whose backends are scripted fakes."""
    settings = Settings(
        llm_provider_chain=chain,
        groq_api_key="k", gemini_api_key="k", huggingface_api_key="k",
        llm_cache_enabled=False,
        **overrides,
    )
    made: dict[str, FakeBackend] = {}

    class Factory:
        def __init__(self, name):
            self.name = name

        def __call__(self, cfg, timeout):
            b = FakeBackend(cfg, timeout, scripts.get(cfg.name, []))
            b.name = cfg.name
            made[cfg.name] = b
            return b

    monkeypatch.setattr(
        P, "_BACKENDS", {n: Factory(n) for n in ("groq", "gemini", "huggingface", "ollama")}
    )
    return P.LLMProvider(settings), made


# --------------------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"verdict": "BID", "score": 7}',
        '```json\n{"verdict": "BID", "score": 7}\n```',
        'Here is the result:\n{"verdict": "BID", "score": 7}\nHope that helps.',
        '```\n{"verdict": "BID", "score": 7}\n```',
    ],
)
def test_extract_json_tolerates_fences_and_prose(raw: str) -> None:
    assert P.extract_json(raw) == {"verdict": "BID", "score": 7}


def test_extract_json_handles_arrays() -> None:
    assert P.extract_json('prose\n[{"a": 1}, {"a": 2}]\ntail') == [{"a": 1}, {"a": 2}]


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(ValueError, match="no parseable JSON"):
        P.extract_json("there is no json here at all")


# --------------------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------------------


class FakeClock:
    """Deterministic clock: sleeping advances time instead of waiting for it."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_token_bucket_allows_up_to_limit_without_waiting() -> None:
    clock = FakeClock()
    b = P.TokenBucket(rpm=5, now=clock.now, sleep=clock.sleep)
    assert sum(b.acquire() for _ in range(5)) == 0.0
    assert clock.slept == []


def test_token_bucket_blocks_past_the_limit() -> None:
    clock = FakeClock()
    b = P.TokenBucket(rpm=2, now=clock.now, sleep=clock.sleep)
    b.acquire()
    b.acquire()
    waited = b.acquire()
    assert waited > 0, "the third call within the window must wait"
    assert waited == pytest.approx(60.01), "it waits until the oldest call ages out"


def test_token_bucket_window_slides() -> None:
    clock = FakeClock()
    b = P.TokenBucket(rpm=2, now=clock.now, sleep=clock.sleep)
    b.acquire()
    b.acquire()
    clock.t += 61.0  # both calls age out
    assert b.acquire() == 0.0, "a cleared window must not throttle"


def test_token_bucket_rpm_floor() -> None:
    assert P.TokenBucket(rpm=0).rpm == 1, "a zero rpm would deadlock the pipeline"


# --------------------------------------------------------------------------------------
# Failover
# --------------------------------------------------------------------------------------


def test_first_provider_serves_when_healthy(monkeypatch) -> None:
    prov, made = build(monkeypatch, {"groq": ["ok"]}, "groq,gemini,huggingface")
    r = prov.generate("hello")
    assert r.text == "ok"
    assert r.provider == "groq"
    assert r.attempts == ["groq"]
    assert "gemini" not in made, "healthy first provider must not touch the next"


def test_rate_limit_falls_through_to_next_provider(monkeypatch) -> None:
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    err = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
    prov, made = build(
        monkeypatch, {"groq": [err, err], "gemini": ["served by gemini"]},
        "groq,gemini,huggingface",
    )
    r = prov.generate("hello")
    assert r.text == "served by gemini"
    assert r.provider == "gemini"
    assert made["groq"].calls == 2, "one retry on the rate-limited provider, then move on"


def test_unavailable_provider_moves_on_immediately(monkeypatch) -> None:
    err = Exception("503 UNAVAILABLE: model experiencing high demand")
    prov, made = build(
        monkeypatch, {"groq": [err], "gemini": ["ok"]}, "groq,gemini"
    )
    assert prov.generate("x").provider == "gemini"
    assert made["groq"].calls == 1, "a 503 is not retried on the same provider"


def test_third_provider_used_when_first_two_fail(monkeypatch) -> None:
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    prov, _ = build(
        monkeypatch,
        {
            "groq": [Exception("429 rate limit")] * 2,
            "gemini": [Exception("503 unavailable")],
            "huggingface": ["last resort"],
        },
        "groq,gemini,huggingface",
    )
    r = prov.generate("x")
    assert (r.provider, r.text) == ("huggingface", "last resort")


def test_strong_tier_downgrades_before_switching_provider(monkeypatch) -> None:
    """Free tiers meter the large models hardest.

    Groq exhausts its daily token budget on llama-3.3-70b long before the 8b model, so a
    rate-limited strong call retries on the same provider's cheap model before moving
    on. Switching provider first would waste a working budget.
    """
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    models: list[str] = []

    class Watcher(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            models.append(model)
            if model == self.cfg.model_strong:
                raise Exception("429 rate limit reached on tokens per day (TPD)")
            return "served by the cheap model", 5, 5

    settings = Settings(llm_provider_chain="groq,gemini", groq_api_key="k",
                        gemini_api_key="k", llm_cache_enabled=False)
    monkeypatch.setattr(
        P, "_BACKENDS",
        {n: (lambda cfg, t: Watcher(cfg, t, [])) for n in ("groq", "gemini")},
    )
    resp = P.LLMProvider(settings).generate("x", tier="strong")

    assert resp.provider == "groq", "it switched provider instead of downgrading tier"
    assert models[0] == settings.groq_model_strong
    assert models[-1] == settings.groq_model_cheap
    assert "downgraded" in resp.attempts[-1]


def test_cheap_tier_is_not_downgraded(monkeypatch) -> None:
    """There is nothing below cheap; retrying the same model would just burn quota."""
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    prov, made = build(
        monkeypatch,
        {"groq": [Exception("429 rate limit")] * 2, "gemini": ["ok"]},
        "groq,gemini",
    )
    assert prov.generate("x", tier="cheap").provider == "gemini"
    assert made["groq"].calls == 2


def test_max_tokens_reaches_the_backend(monkeypatch) -> None:
    """An uncapped section came back at 22,953 characters against a 400-word target."""
    seen: list[int | None] = []

    class Capped(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            seen.append(max_tokens)
            return "ok", 1, 1

    settings = Settings(llm_provider_chain="groq", groq_api_key="k",
                        llm_cache_enabled=False)
    monkeypatch.setattr(P, "_BACKENDS", {"groq": lambda cfg, t: Capped(cfg, t, [])})
    P.LLMProvider(settings).generate("x", max_tokens=900)
    assert seen == [900]


def test_all_providers_failing_reports_every_reason(monkeypatch) -> None:
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    prov, _ = build(
        monkeypatch,
        {
            "groq": [Exception("429 rate limit")] * 2,
            "gemini": [Exception("503 unavailable")],
            "huggingface": [Exception("404 not_found")],
        },
        "groq,gemini,huggingface",
    )
    with pytest.raises(P.AllProvidersFailed) as ei:
        prov.generate("x")
    assert set(ei.value.reasons) == {"groq", "gemini", "huggingface"}


def test_no_configured_provider_raises_actionable_error() -> None:
    s = Settings(llm_provider_chain="groq,gemini", groq_api_key="", gemini_api_key="",
                 huggingface_api_key="")
    with pytest.raises(P.ProviderUnavailable, match=r"\.env"):
        P.LLMProvider(s)


def test_error_classification() -> None:
    assert isinstance(P._classify(Exception("429 Too Many Requests")), P.RateLimited)
    assert isinstance(P._classify(Exception("RESOURCE_EXHAUSTED")), P.RateLimited)
    assert isinstance(P._classify(Exception("503 unavailable")), P.ProviderUnavailable)
    assert isinstance(P._classify(Exception("404 NOT_FOUND")), P.ProviderUnavailable)


# --------------------------------------------------------------------------------------
# Schema validation and reparse
# --------------------------------------------------------------------------------------


def test_schema_validates_good_json(monkeypatch) -> None:
    prov, _ = build(monkeypatch, {"groq": ['{"verdict":"BID","score":7}']}, "groq")
    r = prov.generate("x", schema=Answer)
    assert isinstance(r.parsed, Answer)
    assert (r.parsed.verdict, r.parsed.score) == ("BID", 7)


def test_invalid_json_is_reparsed_once(monkeypatch) -> None:
    prov, made = build(
        monkeypatch,
        {"groq": ["not json at all", '{"verdict":"NO_BID","score":2}']},
        "groq",
    )
    r = prov.generate("x", schema=Answer)
    assert r.parsed.verdict == "NO_BID"
    assert made["groq"].calls == 2


def test_reparse_prompt_carries_the_validation_error(monkeypatch) -> None:
    seen: list[str] = []

    class Recorder(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            seen.append(prompt)
            return super().complete(prompt, system, model, json_mode, max_tokens)

    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=False)
    monkeypatch.setattr(
        P, "_BACKENDS",
        {"groq": lambda cfg, t: Recorder(cfg, t, ["garbage", '{"verdict":"BID","score":1}'])},
    )
    P.LLMProvider(settings).generate("original question", schema=Answer)
    assert len(seen) == 2
    assert "original question" in seen[1]
    assert "could not be parsed" in seen[1]


def test_schema_failure_after_retries_raises(monkeypatch) -> None:
    prov, _ = build(monkeypatch, {"groq": ["nope", "still nope"]}, "groq")
    with pytest.raises(P.LLMError, match="schema validation failed"):
        prov.generate("x", schema=Answer)


def test_json_mode_flag_reaches_the_backend(monkeypatch) -> None:
    flags: list[bool] = []

    class Flagged(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            flags.append(json_mode)
            return super().complete(prompt, system, model, json_mode, max_tokens)

    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=False)
    monkeypatch.setattr(
        P, "_BACKENDS", {"groq": lambda cfg, t: Flagged(cfg, t, ['{"verdict":"a","score":1}'])}
    )
    prov = P.LLMProvider(settings)
    prov.generate("x", schema=Answer)
    prov.generate("y")
    assert flags == [True, False]


# --------------------------------------------------------------------------------------
# Tier routing
# --------------------------------------------------------------------------------------


def test_tier_selects_the_right_model(monkeypatch) -> None:
    models: list[str] = []

    class Watcher(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            models.append(model)
            return super().complete(prompt, system, model, json_mode, max_tokens)

    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=False)
    monkeypatch.setattr(P, "_BACKENDS", {"groq": lambda cfg, t: Watcher(cfg, t, ["a", "b"])})
    prov = P.LLMProvider(settings)
    prov.generate("x", tier="cheap")
    prov.generate("x", tier="strong")
    assert models == [settings.groq_model_cheap, settings.groq_model_strong]
    assert models[0] != models[1]


# --------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------


def test_cache_key_ignores_provider_but_splits_on_tier_and_mode() -> None:
    k = P.ResponseCache.key
    assert k("p", None, "cheap", False) == k("p", None, "cheap", False)
    assert k("p", None, "cheap", False) != k("p", None, "strong", False)
    assert k("p", None, "cheap", False) != k("p", None, "cheap", True)
    assert k("p", "sys", "cheap", False) != k("p", None, "cheap", False)


def test_cache_hit_avoids_a_second_call(monkeypatch, tmp_path) -> None:
    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=True,
                        db_dir=tmp_path)
    monkeypatch.setattr(
        P, "_BACKENDS", {"groq": lambda cfg, t: FakeBackend(cfg, t, ["first", "second"])}
    )
    prov = P.LLMProvider(settings)
    a = prov.generate("same prompt")
    b = prov.generate("same prompt")
    assert (a.text, a.cached) == ("first", False)
    assert (b.text, b.cached) == ("first", True), "second call must come from cache"


def test_cache_hit_is_flagged_not_disguised(monkeypatch, tmp_path) -> None:
    """CLAUDE.md demo discipline: a cache hit must never look like a live call."""
    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=True,
                        db_dir=tmp_path)
    monkeypatch.setattr(
        P, "_BACKENDS", {"groq": lambda cfg, t: FakeBackend(cfg, t, ["x", "y"])}
    )
    prov = P.LLMProvider(settings)
    prov.generate("p")
    prov.generate("p")
    assert [c["cached"] for c in prov.call_log] == [False, True]
    assert prov.usage_summary()["cached"] == 1


# --------------------------------------------------------------------------------------
# Concurrency and telemetry
# --------------------------------------------------------------------------------------


def test_generate_many_preserves_order(monkeypatch) -> None:
    settings = Settings(llm_provider_chain="groq", groq_api_key="k", llm_cache_enabled=False,
                        llm_max_concurrency=4)

    class Echo(FakeBackend):
        def complete(self, prompt, system, model, json_mode, max_tokens=None):
            time.sleep(0.02 if prompt == "a" else 0.0)  # finish out of order
            return f"reply-{prompt}", 1, 1

    monkeypatch.setattr(P, "_BACKENDS", {"groq": lambda cfg, t: Echo(cfg, t, [])})
    out = P.LLMProvider(settings).generate_many(["a", "b", "c"])
    assert [r.text for r in out] == ["reply-a", "reply-b", "reply-c"]


def test_usage_summary_reports_provider_mix(monkeypatch) -> None:
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    prov, _ = build(
        monkeypatch,
        {"groq": ["a", Exception("429 rate limit"), Exception("429 rate limit")],
         "gemini": ["b"]},
        "groq,gemini",
    )
    prov.generate("one")
    prov.generate("two")
    s = prov.usage_summary()
    assert s["calls"] == 2
    assert s["provider_mix"] == {"groq": 1, "gemini": 1}
    assert s["prompt_tokens"] == 22 and s["completion_tokens"] == 44


# --------------------------------------------------------------------------------------
# Live tests — real keys, real network
# --------------------------------------------------------------------------------------


def _live(name: str):
    s = Settings()
    cfg = s.provider(name)
    if not cfg.configured:
        pytest.skip(f"{name} has no key in .env")
    return P.LLMProvider(Settings(llm_provider_chain=name, llm_cache_enabled=False))


def _skip_if_out_of_quota(exc: Exception, name: str) -> None:
    """An exhausted free tier is an account state, not a code defect.

    HuggingFace returns 402 Payment Required once an account's monthly inference credits
    are spent. The chain handles that by failing over, which is the behaviour under test
    elsewhere; a single-provider test has nowhere to fail over to.
    """
    text = str(exc).lower()
    if any(marker in text for marker in ("402", "payment required", "quota", "credits")):
        pytest.skip(f"{name} free-tier quota is exhausted (402); failover covers this")
    raise exc


@pytest.mark.live
@pytest.mark.parametrize("name", ["groq", "gemini", "huggingface"])
def test_live_provider_answers(name: str) -> None:
    prov = _live(name)
    try:
        r = prov.generate("Reply with exactly the word: ready", tier="cheap")
    except P.AllProvidersFailed as exc:
        _skip_if_out_of_quota(exc, name)
    assert "ready" in r.text.lower()
    assert r.provider == name
    assert r.total_tokens > 0, "token accounting must work for the runs table"


@pytest.mark.live
@pytest.mark.parametrize("name", ["groq", "gemini", "huggingface"])
def test_live_json_mode_validates(name: str) -> None:
    prov = _live(name)
    try:
        r = prov.generate(
            "Assess this bid: strong fit, incumbent supplier, 3 competitors. "
            'Return JSON with keys "verdict" (BID or NO_BID) and "score" (integer 1-10).',
            tier="cheap",
            schema=Answer,
        )
    except P.AllProvidersFailed as exc:
        _skip_if_out_of_quota(exc, name)
    assert isinstance(r.parsed, Answer)
    assert r.parsed.verdict in {"BID", "NO_BID"}


@pytest.mark.live
def test_live_failover_survives_a_dead_first_provider() -> None:
    """Point groq at a model that does not exist; the chain must still answer."""
    s = Settings(llm_provider_chain="groq,gemini", groq_model_cheap="no-such-model-xyz",
                 llm_cache_enabled=False)
    if not s.provider("gemini").configured:
        pytest.skip("gemini has no key in .env")
    r = P.LLMProvider(s).generate("Reply with exactly the word: ready")
    assert r.provider == "gemini"
    assert "ready" in r.text.lower()


@pytest.mark.live
@pytest.mark.slow
def test_local_embeddings_and_rerank() -> None:
    """Embeddings and reranking must be local. First run downloads ~220 MB."""
    prov = P.LLMProvider(Settings(llm_provider_chain="ollama"))
    vecs = prov.embed(["GDPR data protection compliance", "annual leave policy"])
    assert len(vecs) == 2 and len(vecs[0]) == 384

    ranked = prov.rerank(
        "What are your data protection commitments?",
        ["We are certified to ISO 27001 and comply with GDPR.",
         "Our canteen serves lunch from noon."],
    )
    assert ranked[0][0] == 0, "the relevant document must rank first"
