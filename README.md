# RFP Copilot v2

A four-plane, thirteen-agent system that turns an RFP into a complete proposal package —
narrative, tables, charts, costings and a compliance matrix — with provenance on every
sentence and automated consistency checks across the whole document.

Runs at **zero marginal cost** on free-tier infrastructure: free-tier cloud generation,
local embeddings, local vector store, local database. No card is required at any point.

**Governing metric:** *automation rate* — the percentage of the final document produced
with zero human input, reported per section type.

## Provider architecture

Generation is **provider-agnostic**. Every model call goes through `src/llm/provider.py`,
which pools three free tiers and fails over between them:

```
groq → gemini → huggingface        (configurable chain; ollama = offline path)
```

Embeddings and reranking stay **local** (`bge-small-en-v1.5`, `ms-marco-MiniLM-L-6-v2`).
They are small, fast on CPU, and cloud-embedding an entire corpus at ingest would exhaust
free-tier rate limits in a single run.

The original plan mandated Ollama-only execution. That was retired on measured evidence
from the build machine (7.7 GB RAM, integrated GPU):

| Model | Throughput | Verdict |
|---|---|---|
| `qwen2.5:7b-instruct` | 0.15 tok/s | unusable — 68 tokens took 452 s |
| `qwen2.5:3b-instruct` | 5.7 tok/s | usable offline, ~2.5 min per section |
| free-tier cloud | fast enough for a live run | primary |

Ollama remains supported and the pipeline still runs end to end with
`LLM_PROVIDER_CHAIN=ollama` — just slowly. See `CLAUDE.md` for the full provider policy.

## Status

Phase 1 of 12 complete. See `RFP_Copilot_v2_Build_Plan.md` for the full plan and
`CLAUDE.md` for the working conventions every phase must respect.

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffold, config, contracts-as-docstrings | done |
| 1 | Data layer: SQLite schema + pydantic contracts | done |
| 2 | Provider wrapper, ingestion, threshold calibration | not started |
| 3–12 | Agents, assurance, orchestration, dashboard, evaluation | not started |

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then put at least one free-tier key in `.env` — no card required for any of them:

| Provider | Get a key |
|---|---|
| Groq | https://console.groq.com/keys |
| Gemini | https://aistudio.google.com/apikey |
| HuggingFace | https://huggingface.co/settings/tokens |

All three is best: the provider chain fails over on rate limits, so pooling three free
tiers is what makes a live end-to-end run survivable.

**Optional — offline path.** Install [Ollama](https://ollama.com) and
`ollama pull qwen2.5:3b-instruct`, then set `LLM_PROVIDER_CHAIN=ollama`. The pipeline
runs with no network and no keys, at roughly 5.7 tok/s.

## Test

```bash
pytest
```

The Ollama liveness check skips with a visible reason if no model server is reachable;
every other test runs fully offline.

## Layout

```
config.py                 settings singleton; thresholds live in config/thresholds.json (Phase 2)
data/                     incoming RFPs, knowledge base, historical Q&A, proofs, templates, eval sets
db/                       SQLite + Chroma + BM25 index
src/llm/provider.py       the only module permitted to call a model
src/models/               SQLite schema and the pydantic contracts agents exchange
src/ingestion/            corpus ingestion and retrieval-threshold calibration
src/agents/               planes 1–3
src/writers/              the five specialist writers
src/assurance/            plane 4
src/workflow/             routing, tracking, assembly
src/orchestrator.py       chains the planes; owns the regeneration loop
app/dashboard.py          Streamlit UI
tests/                    acceptance tests, one set per phase
```
