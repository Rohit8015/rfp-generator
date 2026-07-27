# RFP Copilot — The Complete Guide

*The working of the application, its business use and impact, and everything around it.*

This is the single, self-contained reference. It combines the accessible overview, the
full technical working, the business case, the measured evidence, and the context. For
the shorter cuts see `APP_OVERVIEW.md` (plain-language), `SYSTEM_REPORT.md` (technical
detail), `ASSIGNMENT_REPORT.md` (assignment rubric), and `DEMO.md` (presentation script).

---

## Contents

1. What it is, in one page
2. The business problem
3. Business value and impact
4. Who uses it, and how
5. The end-to-end working
6. The thirteen agents in detail
7. The web application
8. Technical architecture
9. The design principles that make it trustworthy
10. Data, and how the system is set up
11. Measured results
12. How it compares to current practice
13. Limitations and future work
14. Deployment and running it
15. Safety, governance and data hygiene
16. Glossary

---

## 1. What it is, in one page

RFP Copilot is an **agentic AI system that turns a Request for Proposal into a
first-draft response** — narrative, tables, costings, charts and a compliance matrix —
in which **every sentence is traceable to a source**, the **arithmetic is checked by
code**, and anything the organisation **cannot evidence is flagged rather than
fabricated**.

It does three things that generic "let an LLM write it" tools do not:

- It answers the question that comes *before* drafting — **should we bid at all?**
- It produces the **compliance matrix and evidence-gap list** a bid team otherwise
  assembles by hand under deadline pressure.
- It attaches **provenance to every sentence** and **verifies every figure**, so the
  output can survive due diligence rather than merely read well.

It is delivered as a web application: open it, drop in an RFP, and about two minutes later
you have a reviewable proposal package across seven tabs. It runs at **zero marginal
cost** — free-tier cloud language models plus local search — needing only a free API key.

**The governing metric** is the *automation rate*: the share of the document produced
with zero human input, reported honestly, including where it is low and why.

---

## 2. The business problem

### The economics of bidding

A mid-sized B2B consulting or technology firm responds to **60–100 RFPs a year**. Each
response consumes **80–200 hours** of expensive professional time. The win rate is
typically **20–30%**. The arithmetic is unforgiving: **roughly 70% of all bid effort is
spent on proposals that lose.**

### Why bids actually fail

The reasons are rarely about writing quality. They are structural, and they repeat:

1. **A missed mandatory requirement.** Most RFPs score mandatory items pass/fail. Miss
   one — a certification, a registration, a specific capability — and the response is
   disqualified before anyone reads the prose.
2. **Figures that do not reconcile.** A cost table whose components do not sum to the
   stated total is the single most damaging error a proposal can contain, because it is
   the one thing a procurement analyst will always check.
3. **Claims that cannot be evidenced.** Vague assertions written to fill a capability gap
   survive the first read and collapse under buyer due diligence.
4. **Bidding at all.** The most expensive decision in the process is usually the one
   nobody formally makes — pursuing a deal that was unwinnable from the start.

### Why traditional methods struggle

Before AI, RFP response was a manual assembly process: read the RFP and shred it into a
requirements spreadsheet; decide (often on instinct) whether to bid; search a shared
drive of past proposals for reusable answers; write the rest by hand; check the draft
against the compliance matrix manually; and merge the pieces. The content library goes
underused because finding the right past answer is slower than rewriting it, the
bid/no-bid call is not repeatable, and the final compliance check depends on one tired
person not missing a row at 2am.

---

## 3. Business value and impact

The return does not come primarily from writing faster. It comes from four places, in
order of financial impact.

### 3.1 Not bidding — the highest-return output

The bid qualifier recommends **BID / PARTNER_BID / NO_BID** with the driving factors
named. If it correctly kills ten hopeless pursuits a year at 100 hours each, that is
**1,000 hours redirected to winnable work** — worth more than any drafting speedup. Most
firms know they chase bad deals; few have a repeatable, defensible way to say no.

### 3.2 Institutional memory that gets used

Every firm has a knowledge base nobody searches, because retrieval is slower than
rewriting. Hybrid search over a library of approved answers changes the default from
*rewrite* to *reuse*, and the reuse decision (REUSE / ADAPT / SYNTHESISE) tells the writer
which mode they are in before they start.

### 3.3 Compliance coverage — where bids die

Every requirement is traced to a section and a paragraph, RAG-coded, with a coverage
percentage. This is the feature a bid director would pay for on its own: it is a checklist
no human reliably completes under deadline pressure, and missing one mandatory item is
fatal regardless of how good the prose is.

### 3.4 The gap list as a commercial instrument

Knowing on **day one** that you cannot evidence a set of requirements changes the pursuit
— partner, subcontract, invest, or withdraw. Discovering it at day fifteen means writing
vague prose and hoping. The system surfaces gaps and refuses to write around them.

### 3.5 Quantified impact

- **Time:** an end-to-end draft in ~126 seconds versus days of manual assembly; roughly
  **64% of sentences** produced with no human input.
- **Risk reduction:** every injected arithmetic error, duration mismatch, fabricated
  statistic and overclaim was caught in testing — the failure modes that lose bids.
- **Decision quality:** a repeatable bid/no-bid model in place of a gut call.

### 3.6 Where it does *not* add value — stated plainly

- **It will not win the bid.** Win themes, the client relationship and the pricing call
  are human work. It produces a strong, traceable first draft.
- **It is only as good as the corpus.** A firm with no organised past answers gets little
  from it; the search has nothing to find. Payback requires curating the knowledge base —
  the unglamorous part firms skip.
- **Quality bids must not become quantity bids.** Using it to submit twice as many
  responses lowers the win rate and damages reputation.

### 3.7 The honest headline

> The same team responds to more of the *right* RFPs, with every claim traceable to a
> source and every gap visible before the deadline instead of after.

---

## 4. Who uses it, and how

**Primary users:** bid managers, senior stakeholders (for the bid/no-bid call), and
subject-matter experts in a mid-sized B2B technology or professional-services firm.

**Domain:** B2B professional services and fintech — the sample corpus is an Indian
technology-consulting firm responding to financial-services RFPs.

**The single-sentence scope:** given a Request for Proposal document as input, produce a
compliance-checked, evidence-attributed proposal draft as output, with the arithmetic
verified and department-wise action items for everything that needs a human.

- **Input:** one RFP document (PDF, Word, Excel or Markdown).
- **Output:** a proposal draft with sentence-level provenance, a RAG-coded compliance
  matrix, an assurance report, and a routed task list.

---

## 5. The end-to-end working

The system is a pipeline of **thirteen specialised agents** in **four planes**, driven by
a plain Python orchestrator. A request flows through them in sequence, with a feedback
loop at the end.

```
RFP ─► COMPREHENSION ─► STRATEGY ─► GENERATION ─► ASSURANCE ─► package
        parse, extract    proofs,     retrieve,     checks + a
        requirements,     themes,      route to 5    redraft loop
        buyer, bid call   outline      writers       ↓
                                                   escalate to human
```

1. **Comprehension** parses the RFP, extracts and types every requirement, profiles the
   buyer, and decides whether to bid.
2. **Strategy** matches each requirement to evidence, generates win themes, and plans the
   outline — which *is* the compliance-matrix skeleton.
3. **Generation** retrieves supporting context per section and routes each to the right
   specialist writer.
4. **Assurance** checks the assembled draft and re-drafts failing sections with the reason
   fed back, up to twice, then escalates to a human.
5. **Workflow** routes tasks, tracks them, and assembles the final package.

A full run makes ~20 language-model calls; independent sections are drafted concurrently,
and a content-hash cache means re-runs are near-instant.

---

## 6. The thirteen agents in detail

Presented in execution order, which is not numeric order — proof matching (A7) runs before
win themes (A5) because themes must cite proof, and before the architect (A6) because the
outline must know which requirements are unevidenced.

### Plane 1 — Comprehension

**A1 · Document Structurer.** Parses the RFP into a nested tree of sections with
numbering and page references. Deterministic first (heading and numbering patterns); a
model only titles an untitled block, and an outage falls back to a derived title rather
than failing.

**A2 · Requirement Extractor.** Finds every requirement and types it six ways
(explicit question, shall-requirement, implied deliverable, evaluation criterion,
constraint, submission rule), assigns priority via Shipley cue words, and decides the form
its answer will take. A deterministic cue pass carries the mandatory-recall guarantee; an
additive language-model pass finds implied deliverables and can never lower recall.

**A3 · Buyer Intelligence.** Builds the buyer profile — audience, pains, disclosed
evaluation weights, red lines, tone — which is injected into every downstream generation
prompt. Evaluation weights are parsed deterministically because a fabricated weight would
misdirect the emphasis of the whole document.

**A4 · Bid Qualifier.** Scores the pursuit on fit, relationship, incumbency, timing and
competition, plus two named rules: late entry against an entrenched incumbent (a
near-disqualification), and severe price compression (which routes to PARTNER_BID because
it reduces the value of winning, not the chance). Deterministic — no model call.

### Plane 2 — Strategy

**A7 · Proof Point Matcher.** Classifies every requirement STRONG / PARTIAL / GAP against
the evidence library using a local cross-encoder. **A GAP can never cite proof** — the
type system forbids it — so the rule "never write around a gap" cannot be violated.

**A5 · Win Theme Generator.** Produces buyer-focused themes ("your onboarding time
halves"), never seller-focused ("we are a leader"). The model writes the statement;
Python verifies which requirements it actually threads and whether it survives the
two-requirement rule.

**A6 · Response Architect.** Plans the section outline. Two modes: *compliance* (mirror
the buyer's structure, for questionnaires) and *narrative* (a consulting spine, for
briefs). Deterministic, because the guarantee is zero orphaned requirements — an explicit
catch-all section makes that structural.

### Plane 3 — Generation

**A8 · Hybrid Retriever.** Combines keyword search (BM25) and meaning-based search
(embeddings), fuses the rankings, and re-ranks the top results with a cross-encoder.
Returns a list of scored, attributed candidates plus a calibrated reuse decision.

**A9 · Generation Router.** Dispatches each section to one of five writers by its form:
narrative prose and tables (model-driven), cost models and charts and boilerplate
(deterministic). Compliance, legal and unevidenced requirements are carved out to a human
*before* any model call.

### Plane 4 — Assurance

**A10 · Consistency Checker** *(deterministic)* — extracts every number, date and figure
into a fact table and checks that cost components sum to the total, durations reconcile,
and no quantity carries two different values. The arithmetic is done, not judged.

**A11 · Compliance Verifier** *(deterministic)* — traces every requirement to a section
and paragraph, RAG-codes it, and reports coverage. Measured against what was *written*,
not merely planned.

**A12 · Groundedness Checker** *(uses a model)* — checks each factual claim against its
cited source. Findings are advisory flags, never silent deletions.

**A13 · Voice & Risk Reviewer** *(deterministic)* — flags absolute guarantees, unbounded
liability and overclaiming by pattern, and register drift by readability.

### The self-healing loop

Any section failing an **arithmetic** or **blocking risk-language** check is re-drafted
with the failure reason appended to its prompt, up to two retries, then escalated to a
human. Groundedness deliberately does not trigger re-drafting — it is advisory — but it
still reaches the assurance report.

### Workflow

**W1 Task Router** creates a task for every gap and escalation, routed by department
(Legal, Compliance, Information Security, Commercial, Resourcing, Solution Architecture,
Client Development) with a due date worked back from the deadline. **W2 Tracker** manages
status and reminders and never sends anything automatically. **W3 Assembler** merges
sections, injects charts, appends the compliance matrix, and produces Word, Markdown and
the automation report.

---

## 7. The web application

Streamlit-based. You pick or upload an RFP and click **Run pipeline**; per-agent progress
shows for ~2 minutes; then seven tabs:

- **Decide** *(first, by design)* — the bid/no-bid recommendation with sliders to test the
  commercial situation, and the day-one evidence-gap list.
- **Requirements** — every requirement with priority, type, form, evidence verdict and
  assigned section.
- **Draft** — the proposal with every sentence colour-coded by provenance (green reused,
  blue adapted, amber synthesised, grey template/computed, red human-required); hover for
  the source; editable with save-back.
- **Compliance** — the RAG-coded matrix with coverage and paragraph anchors.
- **Assurance** — the consistency result and every finding by severity.
- **Tasks** — every gap and escalation with an owner and due date.
- **Export** — Word, Markdown and the automation report, plus the provenance breakdown.

---

## 8. Technical architecture

**Stack:** Python 3.11+, Streamlit (UI), SQLite (state), ChromaDB (vector store),
rank-bm25 (keyword search), sentence-transformers (embeddings and re-ranking), matplotlib
(charts), python-docx (Word export), pydantic (typed contracts).

**Language models — pooled free-tier cloud with failover.** Every model call goes through
one provider interface. Three free tiers are chained — **Groq → Gemini → HuggingFace** —
so a rate-limited call falls through to the next. A rate-limited strong-tier call
downgrades to the same provider's cheaper model before switching provider, because free
tiers meter the large models hardest. Client-side rate limiting throttles before the
remote does.

**Embeddings and re-ranking stay local** (`bge-small`, `ms-marco-MiniLM`). Cloud embedding
would exhaust free-tier limits in a single ingest pass, and local search keeps retrieval
deterministic and offline.

**Why not local generation?** The original plan mandated local models. Measurement
overturned it:

| Model | Throughput |
|---|---|
| Local 7B (`qwen2.5:7b`) | **0.15 tok/s** — 68 tokens took 452 seconds |
| Local 3B (`qwen2.5:3b`) | 5.7 tok/s |
| Free-tier cloud | ~1.2s per call |

The build machine has 7.7 GB RAM against a 16 GB assumption. Generation moved to cloud;
the architecture did not change, and the pipeline still runs end to end on a local model
if pointed at one.

**Retrieval thresholds are calibrated, never hardcoded.** At ingest, the system computes
all 7,140 pairwise similarities between historical questions and places the REUSE / ADAPT
thresholds at high percentiles of that distribution (REUSE ≥ 0.80, ADAPT ≥ 0.74). This is
unsupervised by necessity: the dataset's own relation labels invert under measurement, so
they are ignored and the corpus itself is used.

---

## 9. The design principles that make it trustworthy

**1. A model for judgement and language; code for anything checkable.** Roughly **40% of
the system is deterministic Python** — cost modelling, arithmetic, compliance, the
bid model, boilerplate. A model asked whether figures add up will say yes; the app does
the addition. This is the single most important decision and the reason the automation
claim is defensible rather than merely fluent.

**2. Rules enforced by the type system, not by convention.** Several safety rules are
impossible to violate because an illegal object cannot be constructed:

| Rule | Enforced by |
|---|---|
| Win probability below 20% forces NO_BID | `BidAssessment` |
| A theme threading fewer than 2 requirements is decorative | `WinTheme` |
| A GAP can never cite proof | `ProofMatch` |
| Each requirement has exactly one primary section | `ResponseOutline` |
| A reused sentence cites one source; a synthesised one cites several | `ProvenanceRecord` |
| Retrieval thresholds are never hardcoded | `ContextPack` requires a calibration version |

**3. Provenance on every sentence.** No untracked text reaches the output; provenance is
produced *by* writing, not attached afterwards, and a section whose prose and records
disagree is refused.

**4. Gaps surfaced, never written around.** If nothing supports a requirement, the app
carves it out visibly and raises a task rather than inventing a claim.

**5. Honest metrics.** The section-level automation rate is reported alongside the
sentence-level one precisely so the flattering number never stands alone.

---

## 10. Data, and how the system is set up

The corpus is synthetic but realistic, representing a technology-consulting firm:

- **10 knowledge-base documents** — capabilities, methodology, security, rate card,
  resourcing, risk taxonomy, subcontracting.
- **120 historical question-answer pairs** — the reuse source.
- **20 proof points** — case studies and references, the evidence library.
- **5 templates** — boilerplate for deterministic fill.
- **3 programme parameter files** — inputs to the cost model.

Ingested into **247 searchable chunks** across the vector store and keyword index. A set
of labelled evaluation files (requirements, retrieval pairs, deal contexts, grounding
pairs, adversarial documents) supports benchmarking.

**A sealed test set** (two held-out RFPs and their gold outputs) is stored outside every
directory the system reads, hashed, and never opened during development — so the final
evaluation is unbiased.

---

## 11. Measured results

Regenerated by `python -m src.evaluate`.

| Metric | Result | Target |
|---|---|---|
| Requirement recall / mandatory | 100% / 100% | ≥90% / 100% |
| Priority accuracy | 100% | ≥85% |
| Bid/no-bid accuracy | 6/6 | 6/6 |
| Retrieval Recall@5 / MRR | 98.0% / 0.957 | >85% / >0.70 |
| Requirement coverage in outline | 100% | 100% |
| Adversarial defects caught | 5 / 5 | all |
| Grounding precision / recall | 0.909 / 1.000 | >0.80 / >0.80 |
| Consistency contradictions | 0 | 0 |
| End-to-end runtime (live) | ~126s | <20 min |
| Automation rate — sentences | 64.2% | — |
| Automation rate — sections | 0.0% | ≥65% |

Backed by **329 automated tests**.

### The caveats, which matter as much as the numbers

- **Extraction's 100% is flattered.** The development RFP labels its own requirements
  inline, so a pattern-matcher scores well without understanding. Read it as "this
  document is easy"; the harder held-out RFPs were not used in development.
- **The 0% section-level automation rate is correct, not broken.** A section counts as
  automated only if no sentence in it needed a human, and nearly every section carries a
  carved-out gap. The 64% sentence figure is the one that distinguishes a mostly-drafted
  document from a barely-started one.
- **The hybrid-beats-dense retrieval target is untestable here.** Dense search alone
  answers 49 of 50 queries, leaving no headroom. Hybrid is kept because it wins on
  exact-term queries.
- **Six bid scenarios cannot fully validate six model parameters.** The 6/6 is reported
  with a stability figure (verdicts survive ±25% weight perturbation) so it is not read as
  stronger evidence than it is.

---

## 12. How it compares to current practice

A commercial category of RFP-response software exists — content-library and auto-response
tools, and newer LLM-native drafting tools. In general, the tools in this category
optimise the *drafting* step and share four gaps that this system was designed to close:

- **No sentence-level provenance** — fluent text with no attribution, so a compliance
  reviewer cannot tell reused from invented.
- **Unchecked arithmetic** — cost figures are model output, and models do not reliably
  add up.
- **Silent gaps** — a missing capability is papered over with boilerplate rather than
  surfaced.
- **Decoupled compliance** — coverage tracking is a separate manual export, if done at
  all.

This system's response to each: provenance on every sentence; deterministic arithmetic
checking; gaps surfaced and never written around; and compliance as a primary,
first-class output. *(Specific claims about named vendors should be verified against their
own documentation before being presented as fact.)*

What makes the approach genuinely different rather than a replica: the **~40%
deterministic split**, the **type-system guardrails**, and the **self-healing
regeneration loop** — none of which is present in a "generate text from a knowledge base"
tool.

---

## 13. Limitations and future work

**Known weaknesses.** The proof matcher is the weakest component — the dataset has no
ground truth for it, so its boundary comes from a threshold sweep rather than labels.
Extraction precision is ~65% (recall was gated at 100%; the surplus is duplicate
captures). The evaluation is largely single-document. Two dataset label sets are
demonstrably wrong and were reported rather than trusted.

**Where the app lags a human expert proposal.** Compared with a polished consulting
proposal, the app produces sections somewhat independently and lacks a single governing
thesis threaded through every section; it has no benefit/ROI narrative to complement the
cost model; and it cites evidence inline rather than composing a tailored references
narrative. Closing these is a research problem, not a bug list.

**Deliberately out of scope.** Live email routing (stubbed), multi-user auth,
fine-tuning, a production vector database, and automatic submission — human approval is
mandatory by design.

---

## 14. Deployment and running it

**Locally:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # add one free API key
python -m src.ingestion.ingest      # build the search index (once)
python -m src.ingestion.calibrate
streamlit run app/dashboard.py
```

**Command line (single run):**
```powershell
python -m src.orchestrator "data/incoming/RFP-A_questionnaire_nbfc.md"
```

**Free cloud hosting.** The app deploys to Streamlit Community Cloud or Hugging Face
Spaces; only the API keys are configured on the platform. The search index builds itself
on first run from the committed corpus, so nothing else needs uploading.

---

## 15. Safety, governance and data hygiene

- **Never auto-sends or auto-submits.** Notifications are recorded, never delivered;
  submission always requires human approval.
- **Secrets stay in environment variables / the platform secrets manager**, never
  committed. A pre-commit hook and a test both block key material from entering git.
- **Compliance, legal and gap requirements always route to a human** — never drafted as
  final by a model.
- **The sealed test set is never read** during development; two tests enforce it.
- **Every provider and model served is logged**, so provider mix is a reportable metric.

---

## 16. Glossary

- **Provenance** — the record of where each sentence came from (reused, adapted,
  synthesised, template, computed, or human-required).
- **GAP** — a requirement with no supporting evidence in the library; surfaced, never
  written around.
- **Automation rate** — the share of output produced with no human input; reported at
  both sentence and section level.
- **Reuse decision** — REUSE / ADAPT / SYNTHESISE / STAKEHOLDER, chosen from calibrated
  retrieval thresholds.
- **Deterministic** — produced by ordinary code with no language-model call.
- **The four planes** — Comprehension, Strategy, Generation, Assurance.
- **Self-healing loop** — automatic re-drafting of a section that fails an arithmetic or
  risk-language check, with the reason fed back, before escalating to a human.

---

*RFP Copilot — turning an RFP into a traceable first-draft response, with every claim
sourced, every number checked, and every gap flagged.*
