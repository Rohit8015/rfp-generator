# RFP Copilot — Complete Feature Reference

Every feature of the application, grouped by subsystem. For each: **what it does**, **how
it works**, the **key parameters**, and **why it exists**. Parameter values are the actual
defaults from the code.

For narrative context see `COMPLETE_GUIDE.md`; for a plain-language overview see
`APP_OVERVIEW.md`.

---

## Contents

- A. Document input and parsing
- B. Corpus ingestion and indexing
- C. Retrieval-threshold calibration
- D. The LLM provider layer
- E. Comprehension agents (A1–A4)
- F. Strategy agents (A5–A7)
- G. Generation: retriever, router and five writers (A8–A9)
- H. Assurance plane (A10–A13) and the regeneration loop
- I. Workflow: routing, tracking, assembly (W1–W3)
- J. Metrics and evaluation
- K. The web application, feature by feature
- L. Safety, guardrails and data hygiene
- M. Cross-cutting engineering features

---

## A. Document input and parsing

### A.1 Multi-format document reader
- **What:** reads an RFP from Markdown, plain text, PDF, Word (`.docx`) or Excel
  (`.xlsx`).
- **How:** format is dispatched on file extension. PDF text is extracted page by page
  with page markers preserved; Word paragraphs recover heading levels from their style,
  and Word/Excel tables are flattened to Markdown pipe rows.
- **Why:** RFPs arrive in every office format; a single reader means the rest of the
  pipeline never sees the difference.
- **Edge cases:** an unsupported extension raises a clear error rather than returning
  empty text; a missing file raises `FileNotFoundError` plainly.

### A.2 Sentence splitter
- **What:** splits text into sentences for cue-word extraction and per-sentence
  provenance.
- **How:** a deterministic splitter that protects common abbreviations (No., Ltd., e.g.,
  Rs., etc.) and decimal numbers so they don't end a sentence.
- **Why:** provenance is per sentence, so sentence boundaries must be stable and offline
  — not a model call.

### A.3 Page-reference tracking
- **What:** records which page each parsed section came from (for PDFs).
- **Why:** lets the compliance matrix and citations point back to a location in the
  source RFP.

---

## B. Corpus ingestion and indexing

### B.1 Four-directory ingestion
- **What:** builds the searchable corpus from exactly four directories — `knowledge_base`,
  `historical_rfps`, `proof_library`, `templates`.
- **Key numbers:** 10 KB documents, 120 Q&A pairs, 20 proof points, 5 templates →
  **247 chunks**.
- **Why:** these four are the only permitted sources; `eval`, `incoming` and archived data
  are never ingested, which protects the sealed test set.

### B.2 Source-aware chunking
- **What:** each source type is chunked by its natural unit.
- **How:**
  - A **Q&A pair** is one chunk (the pair is the unit a human reuses).
  - A **proof point** is one chunk (claim and evidence never separated, so an unevidenced
    claim can't be retrieved alone).
  - A **knowledge-base document** is split on Markdown headings, then by size.
  - A **template** is one chunk (boilerplate is filled whole).
- **Why:** retrieval quality depends on chunks being meaningful units, not arbitrary
  slices.

### B.3 Sliver-merge
- **What:** merges undersized sections forward so no chunk is a bare heading.
- **Key parameters:** `MAX_CHARS = 1400`, `MIN_CHARS = 320`, overlap 180 chars.
- **Why:** a 16-character "## Our Verticals" chunk embeds to noise and competes with real
  content; merging cut KB chunks from 213 to 102.

### B.4 Dual index build
- **What:** builds a **ChromaDB vector index** (dense/semantic) and a **BM25 keyword
  index** over the same chunks.
- **How:** idempotent — re-running rebuilds cleanly rather than duplicating. The BM25
  tokenizer preserves exact terms like GDPR, SOC 2, PSD2.
- **Why:** hybrid retrieval needs both; keyword search catches exact regulatory terms that
  semantic search blurs.

### B.5 First-run bootstrap
- **What:** builds the indices and calibration automatically if they are missing.
- **How:** runs once at app startup, cached; no-ops if the indices already exist.
- **Why:** lets a fresh cloud deploy come up with only API keys configured — everything
  else is built from the committed corpus.

---

## C. Retrieval-threshold calibration

### C.1 Unsupervised percentile calibration
- **What:** derives the REUSE / ADAPT / SYNTHESIZE similarity thresholds from the corpus
  itself.
- **How:** computes all **7,140 pairwise similarities** between historical questions and
  places thresholds at high percentiles — **REUSE at the 99.5th (≈0.80)**, **ADAPT at the
  97th (≈0.74)**.
- **Why:** a REUSE match must be more similar than essentially every unrelated pair in the
  corpus; hardcoded thresholds are meaningless across a change of model or corpus.

### C.2 Label-defect diagnostic
- **What:** reports how far the dataset's shipped relation labels diverge from measurement
  — and refuses to calibrate on them.
- **How:** the shipped labels invert under measurement (SYNTHESIZE pairs score above
  ADAPT), so they are used only as a diagnostic, never to set a threshold.
- **Why:** calibrating on wrong labels would silently corrupt every downstream reuse
  decision.

### C.3 Calibration report
- **What:** writes a human-readable `calibration_report.md` with the distribution,
  thresholds, and the label-defect finding.
- **Why:** the thresholds are an auditable artefact, not a hidden constant.

---

## D. The LLM provider layer

The single gateway for every model call. No other module talks to a model.

### D.1 Pooled multi-provider failover
- **What:** chains providers and falls through on failure — **groq → gemini →
  huggingface** by default; **ollama** as the offline path.
- **How:** a 429/quota error retries once then moves to the next provider; a 503/404 moves
  on immediately. If all fail, the error names every provider's reason.
- **Why:** pooling three free tiers is what makes a live run survive rate limits.

### D.2 Two-tier model selection
- **What:** every call declares a tier — **cheap** (workhorse) or **strong** (assurance,
  long context).
- **Defaults:** Groq `llama-3.1-8b-instant` / `llama-3.3-70b-versatile`; Gemini
  `gemini-3.1-flash-lite` / `gemini-2.5-flash`; HuggingFace Llama-3.1-8B / 3.3-70B.

### D.3 Tier downgrade on rate limit
- **What:** a rate-limited **strong** call retries on the same provider's **cheap** model
  before switching provider.
- **Why:** free tiers meter the large models hardest (Groq's daily token budget on the 70B
  runs out long before the 8B), so downgrading keeps a run alive where switching would
  not.

### D.4 Client-side rate limiting (token bucket)
- **What:** throttles each provider to its per-minute budget before the remote rejects.
- **Defaults:** `groq_rpm 28`, `gemini_rpm 14`, `huggingface_rpm 10`, `ollama_rpm 1000`.
- **Why:** waiting 200ms is cheaper than a 429 round-trip plus a failover.

### D.5 JSON mode with pydantic reparse
- **What:** structured calls are validated against a pydantic schema; an invalid response
  is retried once with the validation error fed back into the prompt.
- **Parameter:** `llm_max_json_retries = 1`.
- **Why:** small models produce imperfect JSON; one guided retry recovers most of it.

### D.6 Output-length capping
- **What:** every generation call can cap `max_tokens`.
- **Why:** an uncapped section returned 22,953 characters against a 400-word target,
  which was unreadable and burned a daily token budget. Writers now cap output from the
  section's target length.

### D.7 Content-hash cache
- **What:** caches responses on a hash of (prompt, system, tier, JSON-mode).
- **How:** the key excludes the provider, so a cached result is reused whoever served it;
  `LLMResponse.cached` is always recorded so the UI can show a hit as a hit.
- **Why:** re-runs are near-instant and cost nothing; demo discipline forbids passing a
  cache hit off as a live call.

### D.8 Concurrent generation
- **What:** `generate_many` runs calls in parallel, preserving input order.
- **Parameter:** `llm_max_concurrency = 4`.
- **Why:** sections are independent; concurrency is what makes a live run watchable.

### D.9 Local embeddings and reranking
- **What:** `embed()` (bge-small, 384-dim) and `rerank()` (ms-marco-MiniLM cross-encoder)
  run **locally**, never on a provider.
- **Why:** cloud embedding would exhaust free-tier limits at ingest; local keeps retrieval
  deterministic and offline. Model construction and inference are lock-guarded for
  thread safety.

### D.10 Usage telemetry
- **What:** logs provider, model, tier, token counts, latency and cache status per call.
- **Output:** `usage_summary()` reports provider mix and token totals into the runs table.
- **Why:** provider mix is a reportable metric and a cost check.

---

## E. Comprehension agents (A1–A4)

### E.1 A1 · Document Structurer
- **What:** parses the RFP into a nested tree with numbering, titles, page refs and raw
  text.
- **How:** deterministic heading/numbering parse first; a model only labels an untitled
  block, and falls back to a derived title if no provider is available.
- **Output:** `DocumentTree`.

### E.2 A2 · Requirement Extractor
- **What:** extracts every requirement and assigns three attributes.
- **Types (6):** EXPLICIT_QUESTION, SHALL_REQUIREMENT, IMPLIED_DELIVERABLE,
  EVAL_CRITERION, CONSTRAINT, SUBMISSION_RULE.
- **Priorities (3):** MANDATORY, WEIGHTED, NICE_TO_HAVE (via Shipley cue words).
- **Forms (7):** PROSE, TABLE, CHART, GANTT, MATRIX, COSTING, APPENDIX (routes generation).
- **How:** a deterministic cue pass (modals, imperatives, declarative rules, table rows,
  section inheritance) carries the recall gate; an additive LLM pass finds implied
  deliverables and can never lower recall. The two are unioned and de-duplicated.
- **Guarantee:** 100% mandatory recall on the labelled set.

### E.3 A3 · Buyer Intelligence
- **What:** builds the `BuyerProfile` injected into every generation prompt.
- **Fields:** audience roles, stated pains, decision constraints, evaluation criteria +
  weights, red lines, tone register, submission rules.
- **How:** facts (especially evaluation weights) are parsed deterministically; only
  interpretive fields (pains, tone) use a model, and the parsed facts always win a
  conflict.

### E.4 A4 · Bid Qualifier *(deterministic)*
- **What:** recommends BID / PARTNER_BID / NO_BID with reasons.
- **Model:** weighted score over five factors — **fit 0.35, relationship 0.20,
  incumbency 0.20, timing 0.15, competition 0.10** — mapped to a win probability (ceiling
  85%).
- **Named rules:** late entry against a strong incumbent applies a 0.35 multiplier; a deal
  size ≤ 0.6× normal routes to PARTNER_BID; win probability < 20% or mandatory fit < 50%
  forces NO_BID.
- **Sensitivity check:** `sensitivity()` reports how often verdicts survive ±25% weight
  perturbation, so a score isn't over-trusted.

---

## F. Strategy agents (A5–A7)

### F.1 A7 · Proof Point Matcher *(cross-encoder, no generative call)*
- **What:** classifies each requirement STRONG / PARTIAL / GAP against the 20-proof
  library.
- **How:** the local cross-encoder scores requirement-vs-proof relevance directly.
  Thresholds on that scale: **PARTIAL floor −10.0, STRONG floor −6.5**. Falls back to
  lexical overlap if no model is available.
- **Hard rule:** a GAP can never cite a proof (enforced by the `ProofMatch` contract).
- **Why cross-encoder:** lexical overlap marked 80% of requirements as GAP; a bi-encoder
  couldn't separate a fraud proof from a gamification proof on an all-fintech corpus.

### F.2 A5 · Win Theme Generator
- **What:** produces 3–5 buyer-side themes.
- **How:** the model writes the statement; Python verifies coverage. A theme threading
  fewer than **2 requirements** is dropped as decorative; seller-side phrasing ("we are a
  leader") is detected and dropped.
- **Contract:** a surviving theme must cover ≥2 requirements and cite ≥1 proof, or it
  cannot be constructed.

### F.3 A6 · Response Architect *(deterministic)*
- **What:** plans the section outline, which is also the compliance-matrix skeleton.
- **Two modes:** COMPLIANCE (mirror the buyer's numbering, for questionnaires) and
  NARRATIVE (a consulting spine, for briefs), chosen from the buyer's submission rules.
- **Guarantee:** zero orphaned requirements — an explicit catch-all section makes this
  structural. Each requirement lands in exactly one primary section.
- **Theme carry:** each surviving theme is carried into the sections holding its
  requirements; the executive summary carries them all.

---

## G. Generation (A8–A9)

### G.1 A8 · Hybrid Retriever
- **What:** returns a `ContextPack` — a list of scored, attributed candidates plus a
  calibrated reuse decision and a confidence.
- **How:** BM25 + dense → **Reciprocal Rank Fusion** → cross-encoder rerank of the top 30
  → top-k. Query expansion adds a keyword paraphrase and the section purpose.
- **Reuse decision:** taken from the raw dense similarity against the calibrated
  thresholds (never a hardcoded number; the pack records its calibration version).
- **Confidence:** normalized margin between the rank-1 and rank-2 scores.

### G.2 A9 · Generation Router
- **What:** dispatches each section to the correct writer by its deliverable form.
- **Routing:** PROSE → narrative; TABLE/MATRIX → structured; COSTING → cost model;
  GANTT/CHART → visual generator; APPENDIX → boilerplate.
- **Guardrail:** compliance, legal and unevidenced (GAP) requirements are carved out to a
  human **before any model call** — a discarded draft still exists, and drafts get copied.
- **Provenance completeness:** the router verifies every section's prose matches its
  provenance records before returning.

### G.3 Narrative writer *(model)*
- **What:** drafts prose carrying the buyer profile, the section's win themes and the
  context pack; cites source IDs inline.
- **Provenance:** derived from the retrieval decision, not the model's self-report —
  REUSE→REUSED (one source), ADAPT→ADAPTED (one source), SYNTHESIZE→SYNTHESIZED (several).
- **Resilience:** on an oversized-prompt failure it retries once on a smaller context
  before escalating.

### G.4 Structured writer *(model, schema-constrained)*
- **What:** produces TABLE/MATRIX sections as typed rows, rendered to clean Markdown/Word
  tables.
- **How:** the model returns JSON rows (never Markdown), so the table is well-formed by
  construction. Row-level provenance; a cited source the retriever never returned is
  stripped as provenance theatre.

### G.5 Cost model / quantitative modeler *(deterministic)*
- **What:** computes the full programme cost.
- **Outputs:** phase person-days and cost, the services/software/cloud/training/PM split,
  contingency, a **reconciled total**, FTE ramp, milestone payment schedule, and an
  indicative payback (only if a benefit figure is supplied — never invented).
- **Multi-currency:** INR and EUR. Reconciliation is enforced at build time — it raises
  if components don't sum to the total.

### G.6 Visual generator *(deterministic)*
- **What:** renders four chart types to PNG — **Gantt, phased investment profile with
  cumulative line, risk heat map, capability map**.
- **How:** charts read the cost model's own numbers, so a chart can't disagree with the
  table beside it. Runs headless (Agg backend).

### G.7 Boilerplate writer *(deterministic)*
- **What:** fills APPENDIX/template sections by pure template fill.
- **How:** templates selected by section identity, never similarity (a retrieval mistake
  would swap one legal appendix for another). Unfilled placeholders stay visible as
  `[[NAME]]` and are reported, never silently deleted.

---

## H. Assurance plane (A10–A13)

### H.1 A10 · Consistency Checker *(deterministic)*
- **What:** extracts every number, date, duration, currency figure and percentage into a
  fact table, then checks internal consistency.
- **Checks:** cost components sum to the stated total; phase durations reconcile with the
  stated programme duration; no tracked quantity carries two values; table percentages
  reconcile.
- **Output:** contradictions localized to a section, with both values shown; findings
  de-duplicated. Facts are swept broadly (currency, %, weeks, months, FTE, person-days,
  years) so the report reflects what was examined, not "0 facts".

### H.2 A11 · Compliance Verifier *(deterministic)*
- **What:** traces every requirement to a section and paragraph anchor; RAG-codes each and
  reports coverage %.
- **Key rule:** coverage is measured against what was **written**, not planned — an
  escalated, undrafted section reduces coverage. GREEN = substantively addressed, AMBER =
  weakly, RED = uncovered. A missed mandatory requirement is a BLOCKER finding.

### H.3 A12 · Groundedness Checker *(model)*
- **What:** checks each factual claim against its cited source, batched.
- **How:** only checkable sentences (figures, superlatives, named standards) are sent —
  connective prose is skipped to save calls and avoid false flags. Findings are advisory
  WARNs, never silent deletions.
- **Measured:** precision 0.909, recall 1.000, false-positive rate 0.100.

### H.4 A13 · Voice & Risk Reviewer *(deterministic)*
- **What:** flags risk language and register drift.
- **Risk patterns:** unqualified guarantees, "100% uptime/accuracy", unlimited liability,
  "zero bugs", "never fail", universal claims, "X% under budget" — each with a severity
  reflecting contractual exposure.
- **Voice drift:** sections more than 1.8 standard deviations from the document's mean
  readability are flagged. Stakeholder briefs are exempt (a brief isn't a client claim).

### H.5 The self-healing regeneration loop
- **What:** re-drafts any section failing an **arithmetic** or **blocking risk-language**
  check, with the failure reason appended to its prompt.
- **Budget:** max 2 retries, then escalate to a human task.
- **Deliberate exclusion:** groundedness (advisory) does not trigger regeneration; it
  would turn every false positive into a wasted redraft and a human task.

### H.6 Carve-out logic
- **What:** a section with a few unevidenced or compliance/legal requirements is drafted
  for the rest and carves those out visibly, rather than escalating the whole section.
- **Why:** one gap among nine should not hand a human nine requirements they didn't need
  to write. Only an all-gap or compliance-subject section escalates wholesale.

---

## I. Workflow (W1–W3)

### I.1 W1 · Task Router *(deterministic)*
- **What:** creates a human task for every gap and escalation.
- **Routing:** by owning department — Legal, Compliance, Information Security, Commercial,
  Resourcing, Solution Architecture, Client Development, or Bid Management by default.
- **Due dates:** worked back from the submission deadline by priority (mandatory 7 days,
  weighted 4, nice-to-have 2), never after the deadline. GAPs already covered by an
  escalated section aren't duplicated.

### I.2 W2 · Task Tracker *(deterministic)*
- **What:** status, overdue marking, reminder simulation.
- **Safety:** `notify()` records what *would* be sent and never sends it — wiring a real
  transport is a deliberate act. Reports blocking mandatory tasks.

### I.3 W3 · Assembler *(deterministic)*
- **What:** merges sections in outline order, injects charts, appends the compliance
  matrix and task list, and exports.
- **Outputs:** Markdown, Word (`.docx` with rendered tables and embedded charts), and the
  automation report. Blocking assurance findings are surfaced at the end of the document.

### I.4 Automation report
- **What:** the headline output — automation rate (section and sentence), per-form
  breakdown, provenance breakdown, GAP list, consistency status, compliance coverage.
- **Why:** the governing metric, computed from provenance records rather than asserted.

---

## J. Metrics and evaluation

### J.1 Retrieval metrics
Recall@1, Recall@5, MRR, nDCG@5 — with a dense-vs-hybrid comparison harness.

### J.2 Extraction metrics
Precision, recall, F1, and per-priority recall against the labelled set.

### J.3 Automation rate (two levels)
- **Section-level:** a section counts only if no sentence needed a human (strict).
- **Sentence-level:** share of sentences with no human input (the informative figure when
  sections carry small carve-outs).

### J.4 Evaluation harness (`python -m src.evaluate`)
Runs every gate, writes `evaluation_report.md` with targets, pass/fail and caveats.
Runs the end-to-end check live by default. The sealed test set is never read unless
`--sealed` is passed (a one-way door with a printed warning).

---

## K. The web application, feature by feature

### K.1 Sidebar
- RFP picker (from `data/incoming`) or file upload (md/txt/pdf/docx).
- **"Use models" toggle** — off runs the deterministic path only.
- Provider chain shown when models are on; a "deterministic path" note when off.
- **Run pipeline** and **Clear run** buttons.

### K.2 Startup bootstrap + secrets bridge
- Builds the index on first run behind a spinner.
- Copies Streamlit Cloud secrets into the environment so the same config works locally
  (.env), from env vars, or on Cloud.

### K.3 Live progress
- Per-stage progress bar with a numbered, readable stage name (execution order, not
  numeric).

### K.4 Metric header
- Four cards: sections clean, sentences automated, coverage, evidence gaps — short labels
  with the detail in tooltips, plus a clean/carve-out/escalated split line.

### K.5 Decide tab *(first)*
- Bid/no-bid recommendation with **six live sliders** (fit, relationship, incumbent,
  timing, competitors, deal size); colour-coded verdict with driving factors.
- **"What we cannot prove"** — the evidence-gap table.

### K.6 Requirements tab
- Full requirement table (ID, priority, type, rendered form, evidence verdict, section,
  text, found-by) with pinned column widths so status columns aren't clipped.

### K.7 Draft tab
- Per-section expanders with a provenance-mix caption.
- **Sentence-level provenance highlighting** (six colours) with source IDs on hover;
  Markdown structure and tables preserved.
- Embedded charts; **editable sections with save-back**.

### K.8 Compliance tab
- RAG-coded matrix with coverage %, section and paragraph anchor per requirement.

### K.9 Assurance tab
- Consistency result with the fact count examined; findings sorted by severity with
  icons.

### K.10 Tasks tab
- Every task with owner, priority, due date, status and covered requirements.

### K.11 Export tab
- Download Markdown, Word and the automation report; provenance breakdown (all six kinds,
  including zeros, so it matches the legend); provider usage JSON.

### K.12 Deployment polish
- `toolbarMode = "minimal"` hides the app-source/GitHub link from viewers; Streamlit
  telemetry disabled; theme set.

---

## L. Safety, guardrails and data hygiene

### L.1 Type-system guardrails
Illegal objects cannot be constructed: winrate < 20% forces NO_BID; a theme must thread
≥2 requirements; a GAP can't cite proof; one primary section per requirement; provenance
source counts must match the kind; a reuse decision requires a calibration version.

### L.2 Compliance/legal/GAP → human
These never reach the model as final; they are carved out or escalated before drafting.

### L.3 Provenance completeness
No untracked text reaches output; a section whose prose and records disagree is refused.

### L.4 Sealed test set protection
Held-out RFPs live outside every ingested/processed path, are hashed, and two tests
enforce that they are never opened during a run.

### L.5 Secret protection
Keys live only in `.env`/platform secrets. A pytest guard scans tracked files for key
shapes and assignments; a pre-commit hook blocks staged key material and any attempt to
commit `.env`.

### L.6 Never auto-send / auto-submit
No email is sent; no response is submitted; human approval is mandatory by design.

---

## M. Cross-cutting engineering features

- **Typed contracts everywhere** — every inter-agent object is a pydantic model; no loose
  dicts cross a boundary.
- **Every agent is a class with one public method** — a uniform, testable shape.
- **Offline degradation** — the whole pipeline runs with `LLM_PROVIDER_CHAIN=ollama`, no
  network and no keys.
- **Graceful failure** — no single agent failure aborts a run; a failed section is
  escalated, so a run always finishes with a package plus a task list.
- **Per-run persistence** — each run records timings, token counts, provider mix and the
  automation rate to SQLite.
- **329 automated tests** — offline (fake backends), live (real providers), and slow
  (local models), separated by markers.
- **Reproducible cost model** — same parameters, same numbers, every time.

---

*Every parameter above is the actual default in the codebase as of this document.*
