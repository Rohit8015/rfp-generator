# RFP Copilot v2 — Multi-Agent Build Plan

**Zero-cost architecture · Claude Code execution guide · 12 phases**

A rebuilt plan for the RFP Copilot. v1 was a five-agent linear pipeline that answered questions. v2 is a **four-plane, thirteen-agent system that produces a complete proposal document** — narrative, tables, charts, costings, compliance matrix — with provenance on every sentence and automated consistency checks across the whole package.

Everything in this plan runs at **zero marginal cost**: local open-weight models, local embeddings, local vector store, local database. No paid API is required at any point. Free-tier cloud APIs are supported as an optional accelerator, never as a dependency.

---

## Part A — Solution

## 1. What changed from v1, and why

| v1 limitation | v2 response |
|---|---|
| Extracted questions only | Requirement Extractor types every requirement: `EXPLICIT_QUESTION`, `SHALL_REQUIREMENT`, `IMPLIED_DELIVERABLE`, `EVAL_CRITERION`, `CONSTRAINT`, `SUBMISSION_RULE` |
| No document planning | Response Architect produces the section outline before drafting; the outline *is* the compliance matrix |
| No narrative spine | Win Theme Generator produces 3–5 Shipley-style themes injected into every generation prompt |
| Prose only | Four specialist writers: narrative, structured/tabular, quantitative, visual |
| Single-hop retrieval, one match | Hybrid retrieval (BM25 + dense) → RRF fusion → cross-encoder rerank → multi-source context pack |
| Hardcoded 0.85 / 0.70 thresholds | Calibrated at ingest from the actual similarity distribution |
| No verification | Assurance plane: consistency, compliance, groundedness, risk-language, voice |
| No feedback | Section-level regeneration loop with a max of 2 retries, failure reason fed back into the prompt |
| Fake LLM confidence | Retrieval-margin + self-consistency confidence |
| Workflow agent doing five jobs | Split into routing, tracking, and assembly |

**Governing metric:** *automation rate* — the percentage of the final document produced with zero human input, reported per section type. This is the project's thesis and its headline number.

---

## 2. Zero-cost technology stack

| Concern | Choice | Cost | Why |
|---|---|---|---|
| Language | Python 3.11+ | Free | — |
| LLM (default) | **Ollama** running `qwen2.5:7b-instruct` (primary) and `llama3.1:8b-instruct` (fallback) | Free, local | Runs on 16 GB RAM; strong instruction-following and JSON output |
| LLM (strong tier) | `qwen2.5:14b-instruct` if ≥24 GB RAM, else same 7B with self-consistency voting | Free, local | Assurance checks benefit from a stronger reasoner |
| LLM (optional cloud) | Gemini / Groq free tier via the same wrapper | Free tier | Speed only; system must pass all tests with Ollama alone |
| Embeddings | `sentence-transformers` → `BAAI/bge-small-en-v1.5` | Free, local | 384-dim, fast on CPU, better than MiniLM on retrieval |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Free, local | Large precision gain, ~30 MB |
| Lexical search | `rank_bm25` | Free | Essential for exact RFP terms (GDPR, PSD2, SOC 2) |
| Vector store | ChromaDB (persistent, local) | Free | Already familiar |
| State | SQLite | Free | Zero setup |
| Doc parsing | `python-docx`, `pypdf`, `openpyxl`, `markdown` | Free | — |
| Doc output | `python-docx` + `markdown` + `weasyprint` (optional PDF) | Free | — |
| Charts | `matplotlib` (Gantt, cost profile, heat maps) + `mermaid` blocks | Free | Deterministic, no LLM |
| Config | `pydantic-settings` + `.env` | Free | — |
| UI | Streamlit | Free | — |
| Orchestration | Plain Python orchestrator + typed pydantic contracts | Free | Transparent, debuggable, explainable to an evaluator |

**Hardware floor:** 16 GB RAM, ~12 GB free disk, CPU-only acceptable (7B q4 quantized runs at roughly 8–15 tokens/sec on modern CPU; GPU optional). No cloud account needed.

**Deliberate non-choices:** no agent framework (LangGraph/CrewAI), no paid vector DB, no fine-tuning, no paid API dependency. Each is a named future-work item, not a gap.

---

## 3. Four-plane architecture

```
                     ┌─────────────────────────────────────┐
   RFP document ────►│  PLANE 1 — COMPREHENSION            │
                     │  A1 Document Structurer             │
                     │  A2 Requirement Extractor (typed)   │
                     │  A3 Buyer Intelligence               │
                     │  A4 Bid Qualifier                    │
                     └──────────────┬──────────────────────┘
                                    ▼
                     ┌─────────────────────────────────────┐
                     │  PLANE 2 — STRATEGY                 │
                     │  A5 Win Theme Generator             │
   Knowledge base ──►│  A6 Response Architect (outline)    │
   Historical Q&A    │  A7 Proof Point Matcher (STRONG/    │
   Proof library     │      PARTIAL/GAP)                   │
                     └──────────────┬──────────────────────┘
                                    ▼
                     ┌─────────────────────────────────────┐
                     │  PLANE 3 — GENERATION               │
                     │  A8  Hybrid Retriever               │
                     │  A9  Generation Router              │
                     │      ├ narrative writer             │
                     │      ├ structured/table writer      │
                     │      ├ quantitative modeler (det.)  │
                     │      ├ visual generator (det.)      │
                     │      └ boilerplate assembler        │
                     └──────────────┬──────────────────────┘
                                    ▼
                     ┌─────────────────────────────────────┐
                     │  PLANE 4 — ASSURANCE                │
                     │  A10 Consistency Checker (det.)     │
                     │  A11 Compliance Verifier (det.)     │
                     │  A12 Groundedness Checker           │
                     │  A13 Voice Harmonizer + Risk Review │
                     └──────────────┬──────────────────────┘
                          fail ─────┘  regenerate section (max 2)
                                    ▼
                     ┌─────────────────────────────────────┐
                     │  WORKFLOW · routing, tracking,      │
                     │  assembly → docx/md + matrix + charts│
                     └─────────────────────────────────────┘
```

`det.` = deterministic Python, no LLM call. Roughly 40% of the system is deterministic, which is what makes the automation rate defensible.

---

## 4. Agent specifications

### Plane 1 — Comprehension

**A1 · Document Structurer** (`agents/structurer.py`)
- In: RFP file path. Out: `DocumentTree` (nested sections with numbering, page refs, raw text).
- Deterministic parse first (heading styles, numbering regex); LLM only to label untitled blocks.
- *Accept:* on the seed narrative RFP, reproduces the section hierarchy with correct numbering.

**A2 · Requirement Extractor** (`agents/requirements.py`)
- In: `DocumentTree`. Out: `list[Requirement]` — `id, source_section, text, req_type, priority, deliverable_form, cue_evidence`.
- `req_type` ∈ the six types above. `priority` ∈ `{MANDATORY, WEIGHTED, NICE_TO_HAVE}` via Shipley cue words: *must/shall/required* → MANDATORY; *should/scored/weighted* → WEIGHTED; *may/preferred/desired* → NICE_TO_HAVE.
- `deliverable_form` ∈ `{PROSE, TABLE, CHART, GANTT, MATRIX, COSTING, APPENDIX}` — this is what routes generation later.
- Deterministic cue-word pass, then LLM pass for implied deliverables, then union + dedupe.
- *Accept:* ≥90% recall against the hand-labelled requirement set; every MANDATORY caught.

**A3 · Buyer Intelligence** (`agents/buyer_intel.py`)
- In: `DocumentTree`. Out: `BuyerProfile` — audience/roles, stated pains, decision constraints, evaluation criteria and weights if disclosed, red-line/disqualifiers, tone register, submission rules.
- This object is passed into **every** downstream generation prompt. It is the highest-leverage object in the system.
- *Accept:* on the XCD seed brief, extracts the four constraints (budget, ROI, success rate, GDPR) and names the CIO/Group Head audience.

**A4 · Bid Qualifier** (`agents/qualifier.py`)
- In: requirements + capability inventory. Out: `BidAssessment` — fit % on MANDATORY, GAP list, effort estimate, winrate estimate, `BID / PARTNER_BID / NO_BID`.
- Deterministic factor model (fit, incumbent, relationship, late entry, competitor count, deal size). Winrate < 20% → automatic NO_BID.
- *Accept:* two crafted deal contexts produce opposite verdicts with the driving factors named.

### Plane 2 — Strategy

**A5 · Win Theme Generator** (`agents/win_themes.py`)
- In: `BuyerProfile` + differentiator library. Out: 3–5 `WinTheme` objects — `statement, buyer_pain_addressed, proof_ids, requirement_ids_covered`.
- **Rule:** a theme threading through fewer than 2 requirements is flagged decorative and dropped.
- Themes are buyer-side ("your operations team cuts cost-to-serve without headcount change"), not seller-side ("we are a leader in X").
- *Accept:* every surviving theme maps to ≥2 requirement IDs and ≥1 proof point.

**A6 · Response Architect** (`agents/architect.py`)
- In: requirements + `BuyerProfile` + themes. Out: `ResponseOutline` — ordered sections, each with `title, purpose, requirement_ids, deliverable_form, target_words, themes_to_carry, source_hints`.
- Two modes: **compliance mode** (mirror the buyer's structure and order — for questionnaires) and **narrative mode** (consulting-proposal structure — for briefs like XCD). Mode chosen from `BuyerProfile.submission_rules`.
- Emits the compliance matrix skeleton as a by-product.
- *Accept:* every requirement is assigned to exactly one primary section; no orphans.

**A7 · Proof Point Matcher** (`agents/proofs.py`)
- In: requirements + proof library. Out: per-requirement `STRONG / PARTIAL / GAP` with source IDs.
- **Hard rule:** GAPs are surfaced, never invented around. A GAP requirement generates a stakeholder brief, not prose.
- *Accept:* a requirement with no matching proof returns GAP and never reaches the narrative writer.

### Plane 3 — Generation

**A8 · Hybrid Retriever** (`agents/retriever.py`)
- BM25 over raw chunks + dense over bge embeddings → **Reciprocal Rank Fusion** → cross-encoder rerank top-30 → return top-k with scores and provenance.
- Query expansion: original text + requirement paraphrase + section purpose.
- Out: `ContextPack` — a **list** of scored, attributed candidates (not one match).
- `reuse_decision` ∈ `{REUSE, ADAPT, SYNTHESIZE, STAKEHOLDER}` from **calibrated** percentile thresholds written to config at ingest, not hardcoded numbers.
- Confidence = normalized margin between rank-1 and rank-2 scores.
- *Accept:* calibration report written; a near-duplicate question returns REUSE with the right source; a novel one returns SYNTHESIZE or STAKEHOLDER.

**A9 · Generation Router** (`agents/generator.py` + `writers/`)

Routes on `deliverable_form`:

| Form | Writer | LLM? |
|---|---|---|
| PROSE | `narrative_writer.py` — carries themes + buyer profile + context pack; cites source IDs inline | Yes |
| TABLE / MATRIX | `structured_writer.py` — emits typed rows, renders to markdown/docx tables | Yes (schema-constrained) |
| COSTING | `quant_modeler.py` — takes program params (duration, phases, FTE curve, blended rate, contingency %) and computes the full cost model | **No** |
| GANTT / CHART | `visual_generator.py` — matplotlib Gantt, phased investment profile, risk heat map, capability map | **No** |
| APPENDIX / boilerplate | `boilerplate.py` — pure template fill | **No** |

- **Guardrail retained and widened:** Compliance, Legal, and any GAP requirement force STAKEHOLDER — never LLM-drafted as final.
- Every output sentence carries provenance: `REUSED(id)` / `ADAPTED(id)` / `SYNTHESIZED([ids])` / `TEMPLATE` / `COMPUTED` / `STAKEHOLDER`.
- *Accept:* each branch produces the right form with a populated provenance map; the quantitative and visual branches make zero LLM calls.

### Plane 4 — Assurance

**A10 · Consistency Checker** (`assurance/consistency.py`) — **deterministic, and the most demo-able component.**
- Extracts every number, date, duration, currency figure and named entity across all sections into a fact table.
- Checks: cost components sum to the stated total; phase durations sum to the program duration; FTE peaks are consistent with the resource table; the same entity is not given two different values; percentages reconcile.
- Out: `ConsistencyReport` with contradiction list and offending section IDs.
- *Accept:* an injected arithmetic error is caught and localized to the section.

**A11 · Compliance Verifier** (`assurance/compliance.py`) — deterministic.
- Every requirement traced to a section and a paragraph anchor. Out: the requirements compliance matrix, RAG-coded, plus a coverage %.
- *Accept:* deleting one section drops coverage and names the uncovered requirement.

**A12 · Groundedness Checker** (`assurance/grounding.py`)
- Every factual claim in generated prose checked against its cited context chunk. Unsupported claims flagged `UNGROUNDED`, not silently retained.
- Implementation: sentence-level NLI-style check via the local model, batched.
- *Accept:* an injected fabricated statistic is flagged.

**A13 · Voice Harmonizer + Risk Reviewer** (`assurance/polish.py`)
- Single pass over the assembled document for register consistency; flags absolute guarantees, unbounded commitments, and overclaiming language.
- *Accept:* "we guarantee 100% uptime" is flagged; tone variance between sections narrows on a readability metric.

**Regeneration loop** (in `orchestrator.py`): any section failing A10–A13 is re-drafted with the failure reason appended to its prompt, max 2 retries, then escalated to a human task. This loop is what makes the system agentic rather than a chain.

### Workflow plane

**W1 Router** — creates tasks for STAKEHOLDER and GAP items, routed by owning department.
**W2 Tracker** — status, due dates, reminder simulation, overdue marking. `notify()` remains a stub with a clean extension point.
**W3 Assembler** (`workflow/assembler.py`) — merges sections in outline order, injects charts, appends the compliance matrix, renders Markdown → docx (and optional PDF), and emits the **automation report**: % automated, per-section source breakdown, GAP list, consistency status.

---

## 5. Repository structure

```
rfp-copilot/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env.example
├── config.py
├── data/
│   ├── incoming/            # RFPs to process
│   ├── knowledge_base/      # capability sheets, policies, methodology
│   ├── historical_rfps/     # past Q&A pairs (reuse source)
│   ├── proof_library/       # case studies, certs, references
│   ├── templates/           # boilerplate sections
│   └── eval/                # labelled train/test sets (see data spec)
├── db/  (rfp_copilot.db · chroma/ · bm25_index.pkl)
├── src/
│   ├── llm/provider.py            # generate(), embed(), rerank(), tier switch
│   ├── models/{schemas.py, db.py}
│   ├── ingestion/{ingest.py, calibrate.py}
│   ├── agents/{structurer,requirements,buyer_intel,qualifier,
│   │           win_themes,architect,proofs,retriever,generator}.py
│   ├── writers/{narrative,structured,quant_modeler,visual_generator,boilerplate}.py
│   ├── assurance/{consistency,compliance,grounding,polish}.py
│   ├── workflow/{router,tracker,assembler}.py
│   ├── orchestrator.py
│   └── utils/{docparse.py, provenance.py, metrics.py}
├── app/dashboard.py
└── tests/
```

---

## 6. Data model additions

New tables beyond v1: **`requirements`**, **`sections`**, **`win_themes`**, **`proof_points`**, **`provenance`**, **`assurance_findings`**, **`runs`** (one row per pipeline execution with the automation rate and timings).

Key enums:
- `req_type` ∈ `{EXPLICIT_QUESTION, SHALL_REQUIREMENT, IMPLIED_DELIVERABLE, EVAL_CRITERION, CONSTRAINT, SUBMISSION_RULE}`
- `priority` ∈ `{MANDATORY, WEIGHTED, NICE_TO_HAVE}`
- `deliverable_form` ∈ `{PROSE, TABLE, CHART, GANTT, MATRIX, COSTING, APPENDIX}`
- `fit` ∈ `{STRONG, PARTIAL, GAP}`
- `reuse_decision` ∈ `{REUSE, ADAPT, SYNTHESIZE, STAKEHOLDER}`
- `provenance_kind` ∈ `{REUSED, ADAPTED, SYNTHESIZED, TEMPLATE, COMPUTED, STAKEHOLDER}`
- `finding_type` ∈ `{CONTRADICTION, UNCOVERED_REQ, UNGROUNDED, RISK_LANGUAGE, VOICE_DRIFT}`

---

## Part B — Delivery

## 7. Project implementation timeline

Twelve phases across **10 weeks**, four waves, each wave gated on an acceptance test before the next is funded with effort. Phases map 1:1 to Claude Code sessions.

| Wave | Weeks | Phases | Gate |
|---|---|---|---|
| **W0 · Foundation** | 1–2 | 0–2 | Local model answers; ingest + calibration report produced |
| **W1 · Comprehension & Strategy** | 3–5 | 3–6 | Requirements extracted at ≥90% recall; outline covers every requirement |
| **W2 · Generation** | 5–7 | 7–8 | Full draft package generated end to end |
| **W3 · Assurance & Delivery** | 8–10 | 9–12 | Consistency + compliance pass; dashboard demo; automation rate reported |

| Phase | Week | Scope | Acceptance test |
|---|---|---|---|
| 0 | 1 | Scaffold: repo tree, requirements.txt, config, CLAUDE.md, Ollama + model pull | `python -c "import src"` clean; `ollama run qwen2.5:7b` responds; `pytest` collects |
| 1 | 1 | Data layer: full schema + all pydantic contracts + enums | Round-trip one row per table; schemas validate on sample payloads |
| 2 | 2 | Provider wrapper (generate/embed/rerank, tier switch, retry, JSON-mode) + ingestion + **threshold calibration** | Chroma + BM25 indices built; `calibration_report.md` written with percentile thresholds |
| 3 | 3 | A1 Structurer + A2 Requirement Extractor | ≥90% recall vs. labelled set; 100% of MANDATORY caught |
| 4 | 3 | A3 Buyer Intelligence + A4 Bid Qualifier | XCD constraints extracted; two deal contexts → opposite verdicts |
| 5 | 4 | A8 Hybrid Retriever (BM25 + dense + RRF + rerank) | Beats dense-only baseline on Recall@5 on the labelled retrieval set |
| 6 | 4–5 | A5 Win Themes + A6 Response Architect + A7 Proof Matcher | Zero orphan requirements; every theme ≥2 requirements; GAPs listed |
| 7 | 5–6 | A9 Router + narrative + structured + boilerplate writers | Each branch correct form; provenance populated on every sentence |
| 8 | 6–7 | Quantitative modeler + visual generator (Gantt, cost profile, heat map, capability map) | Charts render; cost model reconciles to total; **zero LLM calls** in this path |
| 9 | 8 | Assurance plane A10–A13 | Injected error, injected fabrication, and deleted section each caught |
| 10 | 8–9 | Workflow + orchestrator + regeneration loop | One command: RFP → full package + matrix + charts + automation report |
| 11 | 9 | Streamlit dashboard: upload, run, provenance highlighting, matrix view, editable sections, export | Full run from UI; edits persist; download works |
| 12 | 10 | Seed data finalization, E2E tests, evaluation run, README, demo script | `pytest` green; fresh clone runs end to end; metrics table populated |

**Critical path:** Phase 2 (calibration) → Phase 3 (extraction) → Phase 6 (outline) → Phase 10 (orchestrator). Phases 8 and 11 are parallelizable and are the designated de-scope candidates if time compresses.

---

## 8. Resource requirements

### Hardware
| Item | Requirement | Cost |
|---|---|---|
| Workstation | 16 GB RAM min (24 GB comfortable), 12 GB free disk | Existing |
| GPU | Optional; 6 GB VRAM roughly triples generation speed | Existing / none |
| Cloud | None required | ₹0 |

### Software & models
| Item | Source | Licence | Cost |
|---|---|---|---|
| Ollama runtime | ollama.com | MIT | ₹0 |
| qwen2.5:7b-instruct (+14b optional) | Ollama registry | Apache 2.0 | ₹0 |
| llama3.1:8b-instruct | Ollama registry | Llama Community | ₹0 |
| bge-small-en-v1.5 | HuggingFace | MIT | ₹0 |
| ms-marco-MiniLM-L-6-v2 reranker | HuggingFace | Apache 2.0 | ₹0 |
| ChromaDB, SQLite, Streamlit, matplotlib, rank_bm25, python-docx, pypdf | PyPI | Apache/BSD/MIT | ₹0 |

**Total software and infrastructure cost: ₹0.** No API key is required for any acceptance test.

### Effort plan
| Role | Phases | Effort |
|---|---|---|
| Architecture & orchestration (you, driving Claude Code) | 0–2, 10 | ~25 h |
| Agent implementation | 3–9 | ~55 h |
| Dataset curation & labelling | pre-3, ongoing | ~15 h |
| Evaluation, dashboard, demo, writeup | 11–12 | ~20 h |
| **Total** | | **~115 h over 10 weeks (~11 h/week)** |

### Skills / SME inputs
- Prompt design and evaluation methodology — you.
- One reviewer to hand-label the requirement and classification sets (a second pass on ~30 items catches your own labelling bias).
- One domain reader to sanity-check the generated XCD-style output against the reference proposal.

---

## 9. Risks and mitigation

| Risk | L | I | Mitigation |
|---|---|---|---|
| Local 7B model too weak for structured JSON output | M | H | JSON-mode + pydantic validation + 1 automatic reparse retry; fall back to schema-constrained few-shot; 14B tier for assurance |
| Local inference too slow for a live demo | M | M | Cache all agent outputs by content hash; pre-run the demo RFP; show cached run with a live single-section regeneration |
| Calibration set too small to set thresholds | M | M | Bootstrap percentiles; widen the ADAPT band; fall back to rank-based rather than score-based decisions |
| Extraction misses MANDATORY requirements | L | H | Deterministic cue-word pass unioned with LLM pass; recall measured explicitly and gated at 100% for MANDATORY |
| Scope creep across 13 agents | H | H | Phase gates; phases 8 and 11 pre-designated as de-scope candidates; no phase starts before the prior acceptance test passes |
| Groundedness checker produces false positives | M | M | Report as *flags for review*, never auto-delete; tune threshold on the labelled grounding set |
| Seed data too easy, inflating metrics | M | H | Test set includes adversarial items (near-miss questions, novel domains, contradictory requirements) |

---

## 10. Out of scope (choices, not gaps)

- Live email/Gmail routing — stubbed, extension point ready.
- Multi-user auth, permissions, concurrent editing.
- Fine-tuning — retrieval plus prompting is sufficient at this scale.
- Production vector DB (Pinecone/pgvector) — Chroma local is right for an MVP.
- Real client RFPs — synthetic and public data only.
- Automatic submission — human approval is mandatory by design.

---

## Part C — Execution

## 11. `CLAUDE.md` contents

Create this in the repo root in Phase 0.

```markdown
# RFP Copilot — working conventions

## Build discipline
- Build strictly phase by phase. Do not scaffold future phases early.
- After each phase, write AND run its acceptance test before reporting done.
- One commit per phase, message: "Phase N: <scope>".
- If an acceptance test fails, fix and rerun. Never report a phase done on a failing test.

## Code contracts
- Every agent is a class with exactly one public method.
- All inter-agent I/O is a pydantic model from src/models/schemas.py. No loose dicts.
- No LLM call outside src/llm/provider.py. Every call declares a tier: "cheap" or "strong".
- Deterministic components (quant_modeler, visual_generator, consistency, compliance,
  boilerplate) must contain zero LLM calls. Assert this in tests.
- Every generated sentence must carry a provenance record. No untracked text reaches output.

## Zero-cost constraint
- The full pipeline must run with Ollama only. No acceptance test may require a cloud API key.
- Cloud providers are optional accelerators behind the same wrapper interface.

## Safety and integrity rules
- Never invent a proof point to fill a GAP. GAPs surface to a human.
- Compliance, Legal, and all GAP requirements route to STAKEHOLDER — never LLM-drafted as final.
- Never auto-send email. Never auto-submit a response. Drafts only.
- Never hardcode retrieval thresholds; read them from the calibration output in config.
- Keep secrets in .env. Never commit keys or client data.

## Output discipline
- Prefer small, reviewable diffs.
- Log timings and token counts per agent into the runs table.
```

---

## 12. Claude Code execution steps

Run one phase per session. Paste the acceptance criteria into the prompt so Claude Code self-checks. Start each session by having it re-read `CLAUDE.md`.

**Session 0 (setup, do this manually first):**
```bash
curl -fsSL https://ollama.com/install.sh | sh      # or download the installer
ollama pull qwen2.5:7b-instruct
ollama pull llama3.1:8b-instruct
ollama serve
```

**Prompt 0 — Scaffold**
> Read `RFP_Copilot_v2_Build_Plan.md`. Create `CLAUDE.md` exactly as specified in §11, then execute **Phase 0 only**: repo tree per §5, `requirements.txt`, `.env.example`, `config.py` with pydantic-settings, and empty module files with docstrings stating each module's contract. Then run the Phase 0 acceptance test and show me the output. Do not start Phase 1.

**Prompt 1 — Data layer**
> Phase 0 passed. Read `CLAUDE.md`. Execute **Phase 1 only**: implement `src/models/db.py` (full schema per §6, including requirements, sections, win_themes, proof_points, provenance, assurance_findings, runs) and `src/models/schemas.py` (every pydantic contract and enum). Write a throwaway script that round-trips one row per table, run it, show output. Do not start Phase 2.

**Prompt 2 — Provider, ingestion, calibration**
> Phase 1 passed. Execute **Phase 2 only**: `src/llm/provider.py` with `generate(prompt, tier, json_schema=None)`, `embed(texts)`, `rerank(query, docs)`, Ollama default, retry with reparse on invalid JSON, and a cloud provider stub behind the same interface. Then `src/ingestion/ingest.py` (chunk + embed knowledge_base, historical_rfps, proof_library into Chroma, and build the BM25 index) and `src/ingestion/calibrate.py` (sample question pairs, compute the similarity distribution, write percentile thresholds to `config/thresholds.json` plus a human-readable `calibration_report.md`). Acceptance: indices built, calibration report written, a test query returns sensible neighbours. Do not start Phase 3.

**Prompt 3 — Comprehension I**
> Phase 2 passed. Execute **Phase 3 only**: `agents/structurer.py` and `agents/requirements.py` per §4. Deterministic cue-word pass unioned with an LLM pass, deduped. Acceptance: run against `data/eval/requirements_labelled.json` and report recall, precision, and MANDATORY recall. Gate: ≥90% overall recall, 100% MANDATORY recall. Do not start Phase 4.

**Prompt 4 — Comprehension II**
> Phase 3 passed. Execute **Phase 4 only**: `agents/buyer_intel.py` and `agents/qualifier.py`. Acceptance: on the XCD seed brief, BuyerProfile names the audience and the four decision constraints; the qualifier returns opposite verdicts on the two crafted deal contexts in `data/eval/deal_contexts.json`, with driving factors named. Do not start Phase 5.

**Prompt 5 — Hybrid retrieval**
> Phase 4 passed. Execute **Phase 5 only**: `agents/retriever.py` — BM25 + dense, Reciprocal Rank Fusion, cross-encoder rerank of top-30, query expansion, `ContextPack` output with a scored candidate list, calibrated `reuse_decision`, and margin-based confidence. Acceptance: report Recall@5 and MRR on `data/eval/retrieval_pairs.json` for dense-only vs hybrid; hybrid must win. Do not start Phase 6.

**Prompt 6 — Strategy plane**
> Phase 5 passed. Execute **Phase 6 only**: `agents/win_themes.py`, `agents/architect.py`, `agents/proofs.py`. Themes threading through <2 requirements are dropped with a logged reason. Architect supports compliance mode and narrative mode. Acceptance: zero orphan requirements in the outline; every surviving theme maps to ≥2 requirements and ≥1 proof; GAP list printed. Do not start Phase 7.

**Prompt 7 — Generation router and text writers**
> Phase 6 passed. Execute **Phase 7 only**: `agents/generator.py` routing on `deliverable_form`, plus `writers/narrative.py`, `writers/structured.py`, `writers/boilerplate.py`. Every prompt must carry the BuyerProfile and the section's assigned win themes. Every sentence gets a provenance record via `utils/provenance.py`. Compliance/Legal/GAP force STAKEHOLDER. Acceptance: each branch produces the correct form, provenance map is complete, guardrail test passes. Do not start Phase 8.

**Prompt 8 — Quantitative and visual generation**
> Phase 7 passed. Execute **Phase 8 only**: `writers/quant_modeler.py` (phase costs, services/software/cloud/contingency split, reconciled total, FTE ramp, indicative payback) and `writers/visual_generator.py` (matplotlib Gantt, phased investment profile with cumulative line, risk heat map, capability map). Both must be fully deterministic — add a test asserting zero calls into `llm.provider`. Acceptance: charts render to PNG, cost components sum to the stated total. Do not start Phase 9.

**Prompt 9 — Assurance plane**
> Phase 8 passed. Execute **Phase 9 only**: `assurance/consistency.py`, `assurance/compliance.py`, `assurance/grounding.py`, `assurance/polish.py`. Acceptance, using `data/eval/adversarial/`: an injected arithmetic contradiction is caught and localized; a deleted section drops compliance coverage and names the uncovered requirement; an injected fabricated statistic is flagged UNGROUNDED; a "we guarantee 100%" sentence is flagged as risk language. Do not start Phase 10.

**Prompt 10 — Orchestrator and workflow**
> Phase 9 passed. Execute **Phase 10 only**: `workflow/{router,tracker,assembler}.py` and `orchestrator.py` chaining all four planes, including the section-level regeneration loop (max 2 retries, failure reason fed into the prompt, then escalate to a human task). Assembler outputs Markdown + docx, injects charts, appends the compliance matrix, and writes the automation report. Acceptance: one command turns a seed RFP into the full package. Do not start Phase 11.

**Prompt 11 — Dashboard**
> Phase 10 passed. Execute **Phase 11 only**: `app/dashboard.py`. Upload an RFP, run the pipeline with live per-agent progress, show the requirement table with priority and fit, the outline, per-section drafts with provenance highlighting (colour by provenance kind), the compliance matrix view, assurance findings, editable sections with save-back, and export. Acceptance: full run from the UI, edits persist to SQLite, download produces a valid docx. Do not start Phase 12.

**Prompt 12 — Evaluation and packaging**
> Phase 11 passed. Execute **Phase 12 only**: finalize seed data, write `tests/` covering each agent plus an E2E smoke test, run the full evaluation suite over `data/eval/test/` and emit `evaluation_report.md` with the metrics table from the data spec, write the README run-through and a 3-minute demo script. Acceptance: `pytest` green; a fresh clone runs end to end from the README with Ollama only.

**Between phases**, use this standing line:
> Phase N's acceptance test passed. Execute Phase N+1 only, then run its acceptance test. Do not start Phase N+2.

---

## 13. Evaluation metrics to report

| Metric | Target | Where measured |
|---|---|---|
| Requirement recall (overall / MANDATORY) | ≥90% / 100% | Phase 3 |
| Classification accuracy | ≥85% | Phase 4 |
| Retrieval Recall@5 (hybrid vs dense) | hybrid > dense by ≥10 pts | Phase 5 |
| Requirement coverage in outline | 100% | Phase 6 |
| Consistency contradictions in final package | 0 | Phase 9 |
| Groundedness (claims with valid source) | ≥90% | Phase 9 |
| **Automation rate** (sections needing zero human edit) | ≥65% questionnaire, ≥45% narrative | Phase 12 |
| End-to-end runtime, local only | <20 min for a 40-requirement RFP | Phase 12 |

---

## 14. Mapping back to the original architecture

| v1 agent | v2 realization |
|---|---|
| Question Extraction | A1 Structurer + A2 Requirement Extractor (typed, priority-tagged) |
| Classification | A2 priority tagging + A3 Buyer Intelligence |
| Knowledge Retrieval | A8 Hybrid Retriever + calibration + reranking |
| Response Generation | A9 Router + five specialist writers |
| Workflow Management | W1/W2/W3, narrowed to routing, tracking, assembly |
| *(new)* | Plane 2 Strategy — win themes, outline, proof matching |
| *(new)* | Plane 4 Assurance — consistency, compliance, grounding, voice |
| *(new)* | Regeneration feedback loop |

The five original agents all survive. Everything added sits either above them (strategy) or below them (assurance), which keeps the "we built the architecture we proposed, then made it defensible" story clean for the review.
