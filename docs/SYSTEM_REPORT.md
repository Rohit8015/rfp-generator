# RFP Copilot — System Report

A multi-agent system that turns a request for proposal into a complete, traceable
proposal draft.

---

## 1. Purpose

### The problem

A mid-sized technology consultancy responds to somewhere between 60 and 100 RFPs a year.
Each response takes 80–200 hours. The win rate is typically 20–30%. The arithmetic is
brutal: **roughly 70% of all bid effort goes into proposals that lose.**

Worse, the reasons bids fail are rarely about writing quality:

- **A missed mandatory requirement.** Most RFPs score mandatory items pass/fail. Miss one
  and the response is disqualified before anyone reads the prose.
- **Figures that do not reconcile.** A cost table whose components do not sum to the
  stated total is the single most damaging error a proposal can contain, because it is
  the one thing a procurement analyst will certainly check.
- **Claims that cannot be evidenced.** Vague assertions written to fill a gap survive the
  first read and collapse under due diligence.
- **Bidding at all.** The most expensive decision in the process is usually the one
  nobody formally makes.

### What this system does

It does **not** write proposals for you. It produces a **strong first draft in which
every sentence is traceable to a source and every evidence gap is visible on day one**,
plus the compliance matrix and gap list that a bid team otherwise assembles by hand
under deadline pressure.

The governing metric is the **automation rate** — the share of the document produced
with zero human input — reported honestly, including where it is low and why.

---

## 2. Business value

### Where the return actually comes from

**1. Not bidding — the highest-return output.**
The bid qualifier recommends BID / PARTNER_BID / NO_BID with the driving factors named.
If it correctly kills ten hopeless pursuits a year at 100 hours each, that is **1,000
hours redirected to winnable work** — worth more than any drafting speedup. Most firms
know they chase bad deals; few have a repeatable way to say no that survives a partner
insisting otherwise.

**2. Institutional memory that gets used.**
Every consultancy has a knowledge base nobody searches, because finding the right past
answer is slower than rewriting it. Hybrid retrieval over 120 approved answers changes
the default from *rewrite* to *reuse*, and the REUSE/ADAPT/SYNTHESIZE decision tells the
writer which mode they are in before they start typing.

**3. Compliance coverage — where bids actually die.**
Every requirement is traced to a section and a paragraph anchor, RAG-coded, with a
coverage percentage. **This is the feature a bid director would pay for on its own.** It
is a checklist no human reliably completes at 2am before a deadline.

**4. The gap list as a commercial instrument.**
Knowing at day one that you cannot evidence 42 of your requirements changes the pursuit:
partner, subcontract, invest, or withdraw. Discovering it at day fifteen means writing
vague prose and hoping.

### Where it does not add value — stated plainly

- **It will not win the bid.** Win themes, the client relationship, and the pricing call
  are human work.
- **It is only as good as the corpus.** A firm with no organised past answers gets little
  from it. Payback requires curating the knowledge base — the unglamorous part firms skip.
- **Quality bids must not become quantity bids.** Using it to submit 200 responses
  instead of 100 lowers the win rate and damages reputation.

### The honest headline

> The same team responds to more of the *right* RFPs, with every claim traceable to a
> source and every gap visible before the deadline instead of after.

---

## 3. Architecture

### Four planes, thirteen agents

```
                    ┌─────────────────────────────────────────┐
   RFP document ───►│  PLANE 1 · COMPREHENSION                │
                    │  A1 Structurer      A2 Requirements     │
                    │  A3 Buyer Intel     A4 Bid Qualifier    │
                    └──────────────────┬──────────────────────┘
                                       ▼
                    ┌─────────────────────────────────────────┐
   Knowledge base──►│  PLANE 2 · STRATEGY                     │
   Historical Q&A   │  A7 Proof Matcher   A5 Win Themes       │
   Proof library    │  A6 Response Architect                  │
                    └──────────────────┬──────────────────────┘
                                       ▼
                    ┌─────────────────────────────────────────┐
                    │  PLANE 3 · GENERATION                   │
                    │  A8 Hybrid Retriever                    │
                    │  A9 Router ──► 5 specialist writers     │
                    └──────────────────┬──────────────────────┘
                                       ▼
                    ┌─────────────────────────────────────────┐
                    │  PLANE 4 · ASSURANCE                    │
                    │  A10 Consistency    A11 Compliance      │
                    │  A12 Groundedness   A13 Voice + Risk    │
                    └──────────────────┬──────────────────────┘
              fail ◄───────────────────┤ redraft with reason,
              (max 2, then escalate)   │ then human task
                                       ▼
                    ┌─────────────────────────────────────────┐
                    │  WORKFLOW                               │
                    │  W1 Router  W2 Tracker  W3 Assembler    │
                    └─────────────────────────────────────────┘
```

### The design principle that matters most

**Roughly 40% of the system is deterministic Python with no model involved** — costing,
charts, consistency checking, compliance verification, boilerplate, and bid
qualification. This is what makes the automation claim defensible rather than *"we asked
a model and it agreed."*

The division is deliberate and follows one rule: **a model is used for judgement and
language; Python is used for anything checkable.** Asked whether a column of figures adds
up, a model will usually say yes. Asked whether a proof supports a requirement, it says
yes far too readily. Those questions are answered by doing the arithmetic and measuring
the overlap.

### Rules enforced structurally, not by convention

Several of the project's safety rules are impossible to violate because the type system
refuses to construct an illegal object:

| Rule | Enforced by |
|---|---|
| Win probability below 20% forces NO_BID | `BidAssessment` validator |
| A win theme threading fewer than 2 requirements is decorative | `WinTheme` validator |
| A GAP can never cite proof | `ProofMatch` validator |
| Each requirement has exactly one primary section | `ResponseOutline` validator |
| `REUSED(id)` cites one source; `SYNTHESIZED` cites several | `ProvenanceRecord` validator |
| Retrieval thresholds are never hardcoded | `ContextPack` requires a `calibration_version` |

That last one is the most useful: the retriever *cannot* return a reuse decision without
recording which calibration produced it.

---

## 4. The agents, end to end

What follows is the actual execution order, which is not numeric order — A7 runs before
A5 and A6 because win themes must cite proof points and the architect needs to know which
requirements are unevidenced.

### Plane 1 — Comprehension

**A1 · Document Structurer** (`agents/structurer.py`)
Parses the RFP into a nested tree: heading levels, section numbering, page references,
raw text. Deterministic first — heading styles and numbering regex do the work. A model
is used only to title a block that has none, and a provider outage falls back to a
derived title rather than failing the parse.
*Input:* file path (md, pdf, docx, xlsx). *Output:* `DocumentTree`.

**A2 · Requirement Extractor** (`agents/requirements.py`)
Finds every requirement and types it six ways (`EXPLICIT_QUESTION`, `SHALL_REQUIREMENT`,
`IMPLIED_DELIVERABLE`, `EVAL_CRITERION`, `CONSTRAINT`, `SUBMISSION_RULE`), assigns
priority via Shipley cue words, and decides the `deliverable_form` that will route
generation later.

Two passes, unioned: a deterministic cue-word pass carries the MANDATORY recall gate
(recall of must-win requirements cannot depend on a model being reachable), and an LLM
pass adds implied deliverables. **The LLM pass is additive only** — it can never remove
or downgrade a cue-pass requirement, so a bad generation costs precision, never recall.

The cue model handles more than modal verbs. Obligations written as commands — *"Submit
three client references"*, *"Deadline: 30 April"* — carry no *shall* or *must* and were
invisible to the first version, which is how five mandatory requirements were initially
missed.

**A3 · Buyer Intelligence** (`agents/buyer_intel.py`)
Builds the `BuyerProfile`: audience roles, stated pains, decision constraints, disclosed
evaluation criteria and weights, red lines, tone register, submission rules.

**This object is injected into every downstream generation prompt**, which makes it the
highest-leverage object in the system and the one least tolerable to hallucinate.
Anything the document states literally is parsed deterministically — evaluation weights
especially, since a fabricated weight would misdirect the emphasis of every section.
Only the interpretive fields go to a model, and **the deterministic pass always wins a
conflict**.

**A4 · Bid Qualifier** (`agents/qualifier.py`) — *deterministic*
Scores the pursuit on solution fit, relationship depth, incumbency, entry timing and
field size, mapped to a win probability, plus two named rules:

1. **Late entry against a strong incumbent.** The requirement has usually already been
   shaped; the bid is column fodder. A large multiplier, not a small weight, because the
   effect is not linear.
2. **Severe price compression.** This does not reduce the chance of winning, it reduces
   the value of winning — so it routes to PARTNER_BID rather than depressing the winrate.

### Plane 2 — Strategy

**A7 · Proof Point Matcher** (`agents/proofs.py`) — *no generative call*
Classifies every requirement STRONG / PARTIAL / **GAP** against the proof library.

**Hard rule: GAPs are surfaced, never invented around.** The contract makes "GAP with a
proof cited" impossible to construct, so the module cannot violate the rule even by
accident — it can only be wrong about which bucket a requirement lands in.

Matching uses the local cross-encoder. This was not the first design and the path there
is instructive: pure lexical overlap marked 80% of requirements as GAP, because a
requirement asking for *"customer onboarding with KYC and Aadhaar eSign"* and a proof
claiming *"digital lending, TAT from 3 days to 15 minutes"* describe the same capability
with almost no shared vocabulary. Bi-encoder cosine was no better — on a corpus where
everything is fintech, a gamification proof scored as high against a fraud requirement as
the fraud case study did. The cross-encoder reads the pair together and scores relevance
directly, which is the question actually being asked.

**A5 · Win Theme Generator** (`agents/win_themes.py`)
Produces 3–5 buyer-side themes — *"your onboarding time halves"*, never *"we are a leader
in X"*. Seller-side phrasing is detected and dropped.

The division of labour matters: the model writes the statement, because phrasing a
benefit in the buyer's language is a writing task. **Everything checkable is then verified
in Python** — which requirements a theme actually threads, which proofs support it, and
whether it survives the two-requirement rule. A model asked to self-report its own
coverage will overstate it, and that coverage is precisely what the rule tests.

**A6 · Response Architect** (`agents/architect.py`) — *deterministic*
Produces the section outline. **The outline is the compliance matrix skeleton.**

Two modes: *compliance* mirrors the buyer's own section order (for questionnaires), and
*narrative* uses a consulting-proposal spine (for briefs). The mode is chosen from the
buyer's submission rules.

Deterministic because the gate is zero orphan requirements, and an assignment step that
can hallucinate is one that can drop a requirement. An explicit catch-all section is what
makes the zero-orphan guarantee structural rather than hopeful.

### Plane 3 — Generation

**A8 · Hybrid Retriever** (`agents/retriever.py`)
BM25 + dense embeddings → Reciprocal Rank Fusion → cross-encoder rerank of the top 30.
Returns a `ContextPack`: a **list** of scored, attributed candidates, not a single best
match, plus a calibrated reuse decision and a margin-based confidence.

RRF fuses *ranks*, not scores, because BM25 magnitudes are unbounded and corpus-dependent
while cosines sit in a narrow band — any weighted sum of the two is really a weighted sum
of their scales.

**A9 · Generation Router** (`agents/generator.py`)
Dispatches on `deliverable_form` to five writers:

| Form | Writer | Model? |
|---|---|---|
| PROSE | `narrative.py` | Yes |
| TABLE / MATRIX | `structured.py` | Yes, schema-constrained |
| COSTING | `quant_modeler.py` | **No** |
| GANTT / CHART | `visual_generator.py` | **No** |
| APPENDIX | `boilerplate.py` | **No** |

**The guardrail runs before a writer is chosen, not after drafting.** Generating
compliance prose and then discarding it would still spend the call — and worse, the draft
would exist, and drafts get copied.

Compliance, legal and unevidenced requirements are **carved out** of a section rather
than escalating the whole section. A bid team drafts what it can evidence and hands the
rest to a human; the carve-out appears in the document as a visible *"requires input
before submission"* block. Only a section where *every* requirement is a gap, or whose
subject is compliance or legal, goes to a human entire.

Provenance is derived from the retrieval decision, not from the model's account of what
it did. The retriever already knows how the text was built, because it made the decision
that produced the context.

### Plane 4 — Assurance

**A10 · Consistency Checker** — *deterministic, and the most demonstrable component*
Extracts every number, date, duration, currency figure and percentage into a fact table,
then checks: do cost components sum to the stated total, do phase durations reconcile
with the stated programme duration, is any tracked quantity given two different values,
do percentages compute. Every contradiction names the offending section and shows both
values, because a finding a human cannot locate is a finding they will ignore.

**A11 · Compliance Verifier** — *deterministic*
Traces every requirement to a section and paragraph anchor. Emits the RAG-coded matrix
and coverage percentage.

Coverage is measured against what was **written**, not what the outline planned. A
section that was planned, escalated and never drafted reduces coverage — otherwise the
matrix records good intentions.

**A12 · Groundedness Checker** — *uses a model*
Checks each factual claim against its cited source, batched. Findings are **advisory and
never edit**: the plan names false positives as a live risk, and a checker that deletes
on suspicion removes true statements unnoticed. Claims carrying no figures, superlatives
or named standards are skipped without a model call — *"we will work with your team
during discovery"* asserts nothing checkable.

**A13 · Voice Harmoniser + Risk Reviewer** — *deterministic*
Flags absolute guarantees, unbounded liability and overclaiming by pattern. The phrases
that create contractual exposure are a small, known set, and a pattern list is auditable
and extendable by a lawyer. Register drift uses a readability spread rather than an
opinion about tone.

### The regeneration loop

Any section failing assurance is **re-drafted with the failure reason appended to its
prompt**, up to two retries, then escalated to a human task. This loop is what makes the
system agentic rather than a chain.

Groundedness deliberately does *not* trigger regeneration — it is advisory, and letting
an advisory flag escalate a section turned every false positive into a human task.

### Workflow

**W1 Router** creates a task for every gap and escalation, routed by owning department
(Legal, Compliance, Information Security, Commercial, Resourcing, Solution Architecture,
Client Development), with a due date worked back from the submission deadline.

**W2 Tracker** manages status, overdue marking and reminders. `notify()` **records what
would be sent and never sends it** — wiring it to a real transport is a deliberate act
someone has to take.

**W3 Assembler** merges sections in outline order, injects charts, appends the compliance
matrix and task list, renders Markdown and docx, and emits the automation report.

---

## 5. The web application

Streamlit, launched with `streamlit run app/dashboard.py`.

### The user journey

**1. Drop in the RFP.** Upload or pick from `data/incoming/`. Toggle "Use models" off to
run the deterministic path only.

**2. Watch it run.** Per-agent progress with a numbered stage and a readable name.
Roughly two minutes live.

**3. Decide — deliberately the first tab.** The bid/no-bid recommendation with sliders to
test the commercial situation, and below it *"What we cannot prove"* — the gap list. This
comes before the drafts because it is the order in which the outputs are useful: knowing
you cannot evidence 42 requirements changes the pursuit before anyone writes a word.

**4. Requirements.** Every extracted requirement with priority, type, rendered form,
evidence verdict and assigned section.

**5. Draft.** Each section with **sentences colour-coded by provenance**:

| Colour | Meaning |
|---|---|
| Green — REUSED | lifted from an approved past answer |
| Blue — ADAPTED | a past answer reworked for this buyer |
| Amber — SYNTHESIZED | written from several sources |
| Grey — TEMPLATE / COMPUTED | boilerplate or arithmetic, no model involved |
| Red — STAKEHOLDER | a human must write this |

Hovering a sentence shows its source IDs. **Nothing in the document is unattributable** —
this is the claim the whole architecture exists to support, and the thing nobody believes
until they see it. Sections are editable with save-back.

**6. Compliance.** The RAG-coded matrix with coverage percentage and paragraph anchors.

**7. Assurance.** Consistency result with the fact count examined, and every finding by
severity.

**8. Tasks.** Every gap and escalation with a named owner and due date.

**9. Export.** Markdown, docx, and the automation report, plus the provenance breakdown.

---

## 6. Technical decisions and the evidence behind them

### Generation runs on pooled free-tier cloud

The original plan mandated local models only. That was retired on measurement:

| Model | Throughput | Verdict |
|---|---|---|
| `qwen2.5:7b-instruct` (local) | **0.15 tok/s** — 68 tokens in 452s | unusable |
| `qwen2.5:3b-instruct` (local) | 5.7 tok/s | usable offline, ~2.5 min/section |
| Free-tier cloud | ~1.2s per call | primary |

The build machine has 7.7 GB RAM against the plan's 16 GB floor. The architecture did not
change: every call still goes through one provider interface, and the pipeline still runs
end to end on Ollama alone.

**Three free tiers are pooled with failover** (Groq → Gemini → HuggingFace) with
client-side token-bucket throttling. A rate-limited strong-tier call downgrades to the
same provider's cheap model before switching provider, because free tiers meter the large
models far harder.

**Embeddings and reranking stay local** (`bge-small`, `ms-marco-MiniLM`). Cloud embedding
would exhaust free-tier limits in a single ingest pass, and retrieval stays deterministic
and offline.

### Retrieval thresholds are calibrated, never hardcoded

247 chunks are ingested from four directories. Calibration computes all 7,140 pairwise
similarities between historical questions and places thresholds at high percentiles of
that background distribution: **REUSE ≥ 0.7972, ADAPT ≥ 0.7410**.

This is unsupervised by necessity. The dataset ships relation labels, and they do not
survive contact with any embedding of the text — SYNTHESIZE-labelled pairs score *above*
ADAPT-labelled ones. Inspection explains it: *"How do you ensure GDPR compliance?"* is
labelled SYNTHESIZE against *"How do you ensure GDPR compliance for European clients?"*,
which is a near-duplicate. **Five of the six SYNTHESIZE pairs are mislabelled**, so
calibration ignores them and derives from the corpus itself.

### Data hygiene

RFP-D and RFP-E are **sealed**: stored outside every directory ingestion reads, hashed in
`split.json`, and never opened. Two tests enforce it — one rejects any code path built
into the sealed directory, and one monkeypatches `open()` during a full evaluation run to
assert no sealed file is touched.

---

## 7. Measured results

Regenerate with `python -m src.evaluate`.

| Metric | Measured | Target | Result |
|---|---|---|---|
| Requirement recall | 100% | ≥90% | pass |
| MANDATORY recall | 100% | 100% | pass |
| Priority accuracy | 100% | ≥85% | pass |
| Bid/no-bid accuracy | 6/6 | 6/6 | pass |
| Verdict stability under ±25% weight jitter | 100% | ≥95% | pass |
| Retrieval Recall@5 | 98.0% | >85% | pass |
| Retrieval MRR | 0.957 | >0.70 | pass |
| Retrieval nDCG@5 | 0.678 | >0.75 | **miss** |
| Requirement coverage in outline | 100% | 100% | pass |
| Adversarial defects caught | 5 of 5 | all | pass |
| Grounding precision / recall / FPR | 0.909 / 1.000 / 0.100 | >0.80 / >0.80 / <0.10 | at threshold |
| Consistency contradictions | 0 | 0 | pass |
| End-to-end runtime (live) | ~126s | <20 min | pass |
| Automation rate — sentences | 64.2% | — | — |
| Automation rate — sections | 0.0% | ≥65% | **miss** |

### The caveats, which matter as much as the numbers

**Extraction's 100% is flattered.** RFP-A labels its own requirements inline as
`**R-001**`, so a regex scraping those markers scores well without understanding
anything. The extractor does not depend on them, but read the figure as *"this document
is easy"*, not *"extraction is solved"*.

**The hybrid-beats-dense retrieval gate is untestable here.** Dense-only already answers
49 of 50 labelled queries, leaving no headroom for any method to gain 10 points. The
queries are near-paraphrases of their targets — the case dense retrieval handles best.
Hybrid wins on the lexical subset and is retained for exact regulatory terms.

**The 0% section-level automation rate is correct, not broken.** A section counts as
automated only when no sentence in it needed a human, and nearly every section carries at
least one carved-out requirement. A section needing one human sentence is a section
someone must open. The sentence-level figure is reported alongside it because it
distinguishes a mostly-drafted document from a barely-started one.

**Six scenarios cannot validate six parameters.** The bid qualifier's 6/6 is reported with
a stability figure precisely so it is not read as stronger evidence than it is, and two of
the six verdicts are decided by named rules rather than by the weights.

---

## 8. Defects found during the build

Recorded because they are the useful part of the engineering story.

| Defect | Consequence | Cause |
|---|---|---|
| Imperative requirements invisible | 5 mandatory requirements missed | cue model only understood modal verbs |
| `"nda"` matched inside `"ma-nda-tory"` | every mandatory requirement routed to the boilerplate writer | substring matching instead of word boundaries |
| `"ai"` matched inside `"det-ai-led"` | pricing requirement scored as a solution requirement | same class of bug, different module |
| `[A-Z]{2,}` under `IGNORECASE` | every sentence looked checkable — a model call each | case-insensitive flag defeats the pattern |
| Jaccard proof scoring | 80% of requirements marked GAP | divides by union, penalising detailed case studies |
| Chroma client race | 3 of 8 sections silently lost retrieval | concurrent lazy initialisation |
| CrossEncoder race | **interpreter crash, no traceback** | `sentence-transformers` is not thread-safe to construct |
| Newlines → `<br>` | a 20,837-char section rendered inside one `<h2>` | markdown needs line structure |
| Uncapped generation | one 400-word section returned 22,953 chars, exhausting a daily token budget | no `max_tokens` |

Two dataset defects were also found and reported rather than worked around: the
calibration relation labels are demonstrably wrong, and `programme_standard.yaml` states
a 30-month duration whose phases sum to 16.6 months, and describes a ₹35–50 Cr programme
that computes to ₹175.7 Cr.

---

## 9. Limitations and future work

**Known weaknesses**

- **The proof matcher is the weakest component.** The dataset contains no ground truth
  for proof matching, so the PARTIAL/GAP boundary comes from a threshold sweep against
  known-uncovered requirements rather than from labels.
- **Extraction precision is ~65%.** Recall was gated at 100%, and the surplus is largely
  duplicate captures. Precision was not gated and shows it.
- **The evaluation is single-document.** Only RFP-A has a labelled requirement set.
- **Two label sets need a human pass** before REUSE/ADAPT/SYNTHESIZE accuracy can be
  reported at all.

**Deliberately out of scope**

Live email routing (stubbed with a clean extension point), multi-user auth, fine-tuning,
a production vector database, and automatic submission — human approval is mandatory by
design.

---

## 10. Repository

```
src/agents/       A1–A9              src/assurance/    A10–A13
src/writers/      5 specialist writers  src/workflow/  W1–W3
src/llm/provider  the only module permitted to call a model
src/orchestrator  chains the planes, owns the regeneration loop
src/evaluate      produces the metrics table
app/dashboard     Streamlit UI
data/eval/sealed/ RFP-D, RFP-E — never opened
```

**329 tests.** `pytest -m "not live"` runs everything without a network.

Conventions are in `CLAUDE.md`; the demo script is in `docs/DEMO.md`; the original plan
and every departure from it are in `RFP_Copilot_v2_Build_Plan.md` and the commit history.
