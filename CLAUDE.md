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

## Provider policy (revised — supersedes the original zero-cost constraint)
The original plan required Ollama-only execution. That was retired on measured evidence:
on the build machine (7.7 GB RAM, no dedicated GPU) qwen2.5:7b-instruct generates at
0.15 tok/s and qwen2.5:3b-instruct at 5.7 tok/s, against the plan's assumed 8-15 tok/s.
A live end-to-end run was not reachable locally.

- Generation runs on free-tier cloud: Groq (default), Gemini (strong tier and long
  context), HuggingFace (third fallback). All three are free tier; no card required.
- Embeddings and reranking stay LOCAL (bge-small, ms-marco-MiniLM). They are small
  enough to run on this machine, and cloud embedding would exhaust rate limits at ingest.
- Ollama remains a supported backend and the offline degradation path. The pipeline must
  still run end to end with `LLM_PROVIDER=ollama`, just slowly. Do not let cloud-only
  assumptions leak into agent code.
- Every provider sits behind the same `src/llm/provider.py` interface. Agents never know
  which backend served their call.
- Providers are pooled: on rate-limit (429) or failure, fall through to the next provider
  in the configured order. Client-side rate limiting must throttle before the remote does.
- Secrets live in .env only. Never commit a key. Never print a key in logs or reports.

## Safety and integrity rules
- Never invent a proof point to fill a GAP. GAPs surface to a human.
- Compliance, Legal, and all GAP requirements route to STAKEHOLDER — never LLM-drafted as final.
- Never auto-send email. Never auto-submit a response. Drafts only.
- Never hardcode retrieval thresholds; read them from the calibration output in config.
- Keep secrets in .env. Never commit keys or client data.

## Data hygiene (non-negotiable)
- **Sealed test set.** `data/eval/sealed/` holds RFP-D, RFP-E and their golden outputs.
  Never read them, never tune against them, never ingest them. They are deliberately
  outside `data/incoming/` so ingestion cannot reach them. Hashes are in
  `data/eval/split.json`; if a hash changes, every metric after that point is
  contaminated and must be reported as such.
- **Ingestion reads exactly four directories:** knowledge_base, historical_rfps,
  proof_library, templates. It must never read data/eval, data/incoming or
  data/archive_xcd. Assert this in tests.
- **Split on document boundaries, never on items.** Dev is RFP-A/B/C, test is RFP-D/E.
  Splitting individual questions leaks near-duplicates across the boundary and inflates
  every metric.

## Label mapping (dataset vs contracts)
The supplied dataset labels do not use the plan's enums. The contracts in
`src/models/schemas.py` are authoritative because they drive behaviour; dataset labels
are translated on load, never the reverse.
- `deliverable_form`: the dataset labels what the client is buying (PLATFORM, AI_MODEL,
  SLA...). The contract labels how a section is rendered (PROSE, TABLE, GANTT...) and is
  what routes A9 to a writer. Map dataset -> contract in the eval loader.
- `req_type`: the dataset uses SHALL/SHOULD/MAY_REQUIREMENT, which is perfectly
  correlated with its own `priority` field and therefore carries no extra information.
  Derive the contract's six-way `req_type` from the requirement text; take `priority`
  from the dataset directly, since those values already match.

## Demo discipline
- The demo is a live end-to-end run in a classroom. Latency and rate limits are
  first-class design constraints, not afterthoughts.
- Independent agents run concurrently. Per-section generation is parallel.
- Cache agent outputs by content hash. A cache hit must never be presented as a live
  call in the UI — show which is which.
- Every run must degrade gracefully: a provider outage or 429 falls through, and a
  section that cannot be generated is escalated, never faked.

## Output discipline
- Prefer small, reviewable diffs.
- Log timings and token counts per agent into the runs table.
- Log which provider and model served each call. Provider mix is a reportable metric.
