# Process Automation with AI — RFP Response Drafting

**AI & Analytics · Agentic AI · Final Submission**

---

## 1. The process, precisely scoped

**One sentence:** given a Request for Proposal document as input, produce a
compliance-checked, evidence-attributed first-draft response as output.

- **Input:** one RFP document (markdown, PDF, or Word) containing a set of requirements
  a supplier must respond to.
- **Output:** a structured proposal draft in which every sentence is traceable to a
  source, accompanied by a requirements-compliance matrix and a list of requirements the
  organisation cannot evidence.
- **What counts as a good result:** every mandatory requirement is addressed or
  explicitly flagged; no factual claim is unsupported by a cited source; the figures
  reconcile; and the share of the document produced without human input (the
  *automation rate*) is maximised without sacrificing any of the above.

This is one process — drafting a response to an RFP — not a suite. It is decomposed
internally into stages, but it has a single input, a single output, and a single success
definition, which is the test the brief sets.

### Why this process

RFP response is a high-volume, high-stakes, judgement-heavy knowledge process. A
mid-sized consultancy answers 60–100 RFPs a year at 80–200 hours each, and wins roughly
a quarter of them, so the majority of the effort is spent on bids that lose. It is
exactly the kind of process where partial automation with a human in the loop has a
large, measurable payoff — and where a naive "let an LLM write it" approach fails,
because the failure modes (a missed mandatory requirement, a cost table that does not
add up, an unevidenced claim) are precisely the things a language model is worst at.

---

## 2. How the process was done traditionally

Before AI, RFP response was, and in most organisations still is, a manual assembly
process:

1. **Read and shred.** A bid manager reads the RFP and manually extracts every
   requirement into a spreadsheet — the "compliance matrix" or "bid shred" — tagging each
   as mandatory, scored, or optional.
2. **Bid/no-bid.** A senior stakeholder decides whether to pursue the bid, usually in a
   meeting, often on instinct rather than a repeatable model.
3. **Content assembly.** Writers search a shared drive or a "content library" of past
   proposals for reusable answers, copy the closest match, and edit it for the new
   client. Finding the right past answer is frequently slower than rewriting from scratch,
   so the library goes underused.
4. **Drafting.** Subject-matter experts write the sections that cannot be reused.
5. **Review.** A reviewer checks the draft against the compliance matrix by hand, looks
   for internal contradictions, and flags overclaiming — a checklist rarely completed
   thoroughly under deadline pressure.
6. **Assembly.** The pieces are merged, formatted, and the compliance matrix is finalised.

The traditional method is **rule-based and template-driven** at best. Its weaknesses are
well known to anyone who has run a bid desk: the content library is write-only, the
bid/no-bid call is not repeatable, and the final compliance check depends on one tired
person at 2am not missing a row.

---

## 3. How the process is done now with AI

> **Citation note for the submission.** The category below is real and the named vendors
> exist, but this document does NOT assert specific statistics, customer numbers, or
> dated claims, because those must be cited from a primary source. Each place a specific
> figure belongs is marked `[VERIFY + CITE]`. Before submitting, confirm each vendor's
> current capability from its own documentation or a credible third-party review and
> replace the placeholder with a citation. Do not submit an uncited figure.

A commercial category of **RFP-response automation software** now exists. The main
approaches:

**Content-library and auto-response tools.** Products such as **Responsive (formerly
RFPIO)**, **Loopio**, and **Ombud** maintain a curated library of approved question-answer
pairs and use search plus, increasingly, LLMs to auto-populate answers to incoming
questionnaires. Traditionally these relied on keyword or semantic search over the
library; more recent versions add generative drafting. `[VERIFY + CITE: each vendor's
current generative capability from its own product documentation]`

**LLM-native drafting tools.** Newer entrants (for example **AutoRFP.ai** and similar)
lead with generative drafting from a knowledge base rather than treating search as
primary. `[VERIFY + CITE]`

**General-purpose copilots.** Microsoft Copilot and Google's equivalents are used
ad-hoc for RFP drafting without any RFP-specific structure, compliance tracking, or
provenance. `[VERIFY + CITE]`

**The common limitations of current AI practice**, which motivate this project's design:

- Most tools optimise the *drafting* step and treat compliance tracking as a separate
  manual export, if at all.
- Generative drafting typically produces fluent text with **no provenance** — a reviewer
  cannot see which sentence came from an approved source and which the model invented.
- The **bid/no-bid decision** and the **evidence-gap analysis** are largely outside the
  scope of these tools.
- Arithmetic in cost tables is not checked by the tool; it is a language model's output,
  and language models do not reliably add up.

`[VERIFY + CITE: support the four limitations above with at least one third-party review
or analyst note, e.g. a G2/Gartner category page or a practitioner article. If a claim
cannot be sourced, soften it to "in the tools reviewed for this project" and list which.]`

The design in this project responds directly to these four gaps.

---

## 4. The proposed solution

### 4.1 Design thesis

**Use a language model for judgement and language; use deterministic code for anything
checkable.** Roughly 40% of the system is plain Python with no model involved — cost
modelling, chart generation, consistency checking, compliance verification, boilerplate,
and the bid/no-bid model. This is what makes the automation claim defensible rather than
"we asked a model and it agreed", and it is the single most important design decision.

### 4.2 Architecture

A four-plane, thirteen-agent pipeline behind a plain Python orchestrator.

```
RFP ─► COMPREHENSION ─► STRATEGY ─► GENERATION ─► ASSURANCE ─► package
       (parse, extract  (proofs,    (retrieve,     (checks + a
        requirements,    themes,     route to 5     redraft loop)
        buyer, bid call)  outline)    writers)
```

- **Comprehension** parses the RFP, extracts and types every requirement, profiles the
  buyer, and makes the bid/no-bid call.
- **Strategy** matches each requirement to evidence (STRONG / PARTIAL / **GAP**),
  generates buyer-side win themes, and plans the section outline — which *is* the
  compliance matrix skeleton.
- **Generation** retrieves supporting context and routes each section to one of five
  writers: narrative and tabular (model-driven), cost model, charts, and boilerplate
  (deterministic).
- **Assurance** checks arithmetic, requirement coverage, factual grounding, and risk
  language, then re-drafts any failing section with the reason fed back — up to twice,
  then escalates it to a human.

Full agent-by-agent detail is in `docs/SYSTEM_REPORT.md`.

### 4.3 The key design decisions, and why each beats current practice

| Decision | Why | Beats current practice by |
|---|---|---|
| Provenance on every sentence | a reviewer must see reused vs adapted vs invented | closing the "no provenance" gap in generative tools |
| GAPs surfaced, never written around | an unevidenced claim collapses under due diligence | making evidence gaps a day-one output, not a post-hoc discovery |
| Deterministic compliance matrix | missing one mandatory requirement disqualifies a bid | making compliance the primary output, not a manual export |
| Deterministic arithmetic checking | a cost table that does not sum is the error buyers always catch | checking figures the LLM tools leave unchecked |
| A repeatable bid/no-bid model | the most expensive decision is usually the one nobody formally makes | adding a step the drafting tools omit entirely |
| Calibrated, not hardcoded, retrieval thresholds | reuse decisions must reflect the actual corpus | avoiding the brittle fixed thresholds of first-generation tools |

---

## 5. Build and test

The system is fully implemented and tested: **329 automated tests**, an end-to-end run in
about 126 seconds live, and a Streamlit web application for interactive use. The
evaluation harness (`python -m src.evaluate`) regenerates every figure below.

### 5.1 The comparison the brief asks for — variations tried

The brief's central requirement is a comparison across model types, architectures and
feature sets. Four were run as genuine experiments during the build, each with a measured
outcome that changed the design.

**Experiment 1 — Generation backend (model type).**

| Variation | Throughput | Decision |
|---|---|---|
| Local `qwen2.5:7b` | 0.15 tok/s (68 tokens in 452s) | rejected — unusable on the 7.7 GB build machine |
| Local `qwen2.5:3b` | 5.7 tok/s | kept as the offline fallback only |
| Pooled free-tier cloud | ~1.2s per call | **chosen as primary** |

The original plan assumed 8–15 tok/s for a local 7B. Measurement showed 0.15, roughly
60–100× slower, which forced generation onto free-tier cloud behind an unchanged provider
interface. This is the clearest example of benchmarking overturning a design assumption.

**Experiment 2 — Retrieval architecture (feature set).**

| Variation | Recall@5 | MRR | nDCG@5 |
|---|---|---|---|
| Dense only | 98.0% | 0.957 | 0.705 |
| Hybrid (BM25 + dense + RRF) | 98.0% | 0.940 | 0.694 |
| Hybrid + cross-encoder rerank | 98.0% | 0.957 | 0.678 |

The finding here is itself a result: on this benchmark **dense retrieval saturates at
98%**, so the planned "hybrid beats dense by 10 points" gate is untestable. Hybrid is
retained because it wins on the small lexical-dependent subset (exact terms such as
GDPR), which is where BM25 earns its place — but the honest conclusion is that the
benchmark is too easy to separate the architectures, and that is reported rather than
hidden.

**Experiment 3 — Proof matching (three architectures for the same task).**

| Variation | Result on RFP-A |
|---|---|
| Lexical Jaccard overlap | 80% of requirements marked GAP — unusable |
| Bi-encoder cosine similarity | could not separate a fraud proof from a gamification proof |
| **Cross-encoder relevance** | **separates covered from uncovered cleanly** |

This is the most instructive comparison. Lexical matching failed because a requirement
and a proof describe the same capability in different words. A bi-encoder failed because
on an all-fintech corpus everything is topically close. The cross-encoder, which reads
the requirement and the proof together, was the only architecture that answered the
question actually being asked.

**Experiment 4 — Requirement extraction (feature set).**

| Variation | Recall | MANDATORY recall | Precision |
|---|---|---|---|
| Deterministic cue pass only | 100% | 100% | 65% |
| Cue pass + LLM implied-deliverable pass | 100% | 100% | 40% |

The deterministic pass alone meets the recall gate, so it is what the gate runs on — a
provider outage cannot change whether extraction passes. The LLM pass is additive: it
finds implied deliverables at the cost of precision, and can never lower recall.

### 5.2 Benchmark results

Measured on the development set (`data/eval/`), with the sealed test set (RFP-D, RFP-E)
untouched.

| Metric | Result | Target |
|---|---|---|
| Requirement recall / MANDATORY | 100% / 100% | ≥90% / 100% |
| Priority accuracy | 100% | ≥85% |
| Bid/no-bid accuracy | 6/6 | 6/6 |
| Retrieval Recall@5 / MRR | 98.0% / 0.957 | >85% / >0.70 |
| Requirement coverage in outline | 100% | 100% |
| Adversarial defects caught (arithmetic, duration, entity, fabrication, overclaim) | 5 / 5 | all |
| Grounding precision / recall / FPR | 0.909 / 1.000 / 0.100 | >0.80 / >0.80 / <0.10 |
| Consistency contradictions | 0 | 0 |
| End-to-end runtime (live) | ~126s | <20 min |
| Automation rate — sentences | 64.2% | — |
| Automation rate — sections | 0.0% | ≥65% |

### 5.3 Reading the results honestly

Three results need their caveat stated, because a benchmark reported without its
limitations is not evidence:

- **Extraction's 100% is flattered.** The development RFP labels its own requirements
  inline, so a pattern-matcher scores well without understanding. Read it as "this
  document is easy". The two held-out RFPs, which are harder, were deliberately not used
  during development.
- **The 0% section-level automation rate is correct, not broken.** A section counts as
  automated only if no sentence in it needed a human, and nearly every section carries at
  least one carved-out unevidenced requirement. The 64% sentence-level figure is the one
  that distinguishes a mostly-drafted document from a barely-started one.
- **Six bid scenarios cannot validate six model parameters.** The 6/6 accuracy is
  reported with a stability figure (100% of verdicts survive ±25% weight perturbation) so
  it is not read as stronger evidence than it is.

---

## 6. Final recommendation

**On how the process should be done.** RFP response should be run as a
**human-supervised pipeline, not a fully automated one**. The evidence is that the
valuable, reliable parts of the process are the deterministic ones — compliance tracking,
arithmetic checking, evidence-gap surfacing, and the bid/no-bid model — and the
model-driven drafting is best treated as a strong first draft that a human edits, not a
finished product. The single most valuable output is not the prose; it is the compliance
matrix and the gap list, available on day one.

**On the model and configuration, justified by the benchmarks:**

- **Generation:** pooled free-tier cloud (Groq primary), because local inference is
  60–100× too slow on commodity hardware (Experiment 1). Keep a local fallback so the
  pipeline degrades rather than fails.
- **Retrieval:** hybrid + cross-encoder rerank, despite parity with dense on this
  benchmark, because it is strictly better on exact-term queries and the cost is trivial
  (Experiment 2).
- **Proof matching:** cross-encoder, the only architecture of three that separated
  covered requirements from uncovered ones (Experiment 3).
- **Extraction:** deterministic cue pass as the gated backbone, with an additive LLM pass
  for recall of implied deliverables (Experiment 4).

**On where this beats current practice:** by making compliance coverage, evidence gaps,
sentence-level provenance, and arithmetic correctness first-class, deterministic outputs
rather than by-products of a generative step. The claim is not "AI writes your proposals"
— it is "the same team responds to more of the right RFPs, with every claim traceable and
every gap visible before the deadline instead of after."

---

## 7. What is still open

Stated because honest benchmarking is part of the brief:

- The evaluation is largely single-document; only one RFP has a fully labelled
  requirement set.
- The proof matcher's PARTIAL/GAP boundary is set from a threshold sweep, not from
  labelled ground truth, because the dataset contains none for that task.
- Two label sets shipped with the dataset are demonstrably wrong (the calibration
  relations invert under measurement) and were reported and worked around rather than
  trusted.
- The current-AI-practice citations in Section 3 are placeholders and **must be filled
  from primary sources before submission.**

---

*Supporting material: `docs/SYSTEM_REPORT.md` (full architecture and every agent),
`docs/DEMO.md` (a three-minute walkthrough), `output/evaluation_report.md` (regenerated
benchmarks), and the commit history (each build phase and every departure from the
original plan).*
