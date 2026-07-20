# RFP Copilot v2

A four-plane, thirteen-agent system that turns an RFP into a complete proposal package —
narrative, tables, charts, costings and a compliance matrix — with provenance on every
sentence and automated consistency checks across the whole document.

Runs at **zero marginal cost**: local open-weight models, local embeddings, local vector
store, local database. No paid API is required at any point.

**Governing metric:** *automation rate* — the percentage of the final document produced
with zero human input, reported per section type.

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

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
```

Install [Ollama](https://ollama.com), then pull the models:

```bash
ollama pull qwen2.5:7b-instruct
ollama pull llama3.1:8b-instruct
ollama serve
```

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
