# RFP Copilot — What the App Is and How It Works

A plain-language guide to the application. For the deep technical rationale see
`SYSTEM_REPORT.md`; for the assignment write-up see `ASSIGNMENT_REPORT.md`.

---

## In one paragraph

RFP Copilot reads a Request for Proposal and produces a first-draft response in which
**every sentence is traceable to a source**, the **arithmetic is checked**, and anything
the organisation **cannot evidence is flagged rather than faked**. It also answers the
question that comes before drafting — *should we even bid?* — and produces the compliance
matrix and task list a bid team would otherwise assemble by hand. It is a web app you
open in a browser, drop an RFP into, and get a reviewable proposal package out of in
about two minutes.

---

## The problem it solves

A consulting firm answers dozens of RFPs a year, spending 80–200 hours on each, and wins
maybe a quarter. Most of that effort goes into bids that lose. And bids usually fail for
reasons that have nothing to do with writing quality:

- a **mandatory requirement is missed**, which disqualifies the response outright;
- a **cost table does not add up**, which a buyer's procurement team always catches;
- a **claim cannot be backed up**, which survives the first read and collapses under
  scrutiny.

The app is built to prevent exactly these three failures, and to make the expensive
bid/no-bid decision a repeatable one rather than a gut call.

---

## What it produces

From a single RFP document, the app generates:

1. **A bid recommendation** — BID / PARTNER_BID / NO_BID, with the reasons named.
2. **A typed requirement list** — every requirement found, classified and prioritised.
3. **An evidence assessment** — for each requirement: STRONG, PARTIAL, or **GAP**.
4. **A drafted proposal** — section by section, with every sentence colour-coded by where
   it came from.
5. **A compliance matrix** — every requirement traced to a section, RAG-coded, with a
   coverage percentage.
6. **An assurance report** — arithmetic checks, unsupported-claim flags, risk-language
   warnings.
7. **A task list** — every gap and every escalation, routed to an owning department.
8. **Exports** — Word document, Markdown, and an automation report.

---

## How you use it — the seven tabs

You open the app, pick an RFP in the sidebar (or upload one), and click **Run pipeline**.
About two minutes later you have seven tabs:

**1 · Decide** — *the first tab on purpose.*
The bid/no-bid recommendation, with sliders to test the commercial situation (fit,
relationship, incumbent strength, timing, competition, deal size). Below it, **"What we
cannot prove"** — the list of requirements with no supporting evidence. This comes first
because the most valuable decision is whether to bid at all, and knowing your evidence
gaps on day one changes how you pursue the deal.

**2 · Requirements** — every requirement the app extracted, with its priority, type, the
form its answer will take, its evidence verdict, and the section it was assigned to.

**3 · Draft** — the proposal itself, section by section, with **every sentence
colour-coded by provenance**:

| Colour | Meaning |
|---|---|
| Green | reused from an approved past answer |
| Blue | adapted from a past answer for this buyer |
| Amber | synthesised from several sources |
| Grey | boilerplate or arithmetic — no AI involved |
| Red | a human must write this |

Hover any sentence to see its exact source. Sections are editable, and edits save back.

**4 · Compliance** — the RAG-coded matrix: each requirement, the section that answers it,
a paragraph anchor, and the overall coverage percentage.

**5 · Assurance** — the consistency result (did the numbers reconcile?) and every finding
by severity, including any unsupported claims or overclaiming language.

**6 · Tasks** — every gap and escalation with an owner (Legal, Compliance, Commercial,
etc.) and a due date worked back from the submission deadline.

**7 · Export** — download the Word, Markdown and automation report, and see the breakdown
of where the text came from.

---

## How it works under the hood

The app is a pipeline of **thirteen specialised agents** organised into four stages. You
do not need to know them to use it, but understanding the shape explains why it behaves
the way it does.

**Stage 1 — Comprehension.** It parses the RFP into a structure, extracts and types every
requirement, profiles the buyer (their priorities, constraints, tone), and makes the
bid/no-bid call.

**Stage 2 — Strategy.** It matches each requirement to the evidence library (STRONG /
PARTIAL / GAP), generates buyer-focused win themes, and plans the section outline — which
doubles as the compliance-matrix skeleton.

**Stage 3 — Generation.** For each section it retrieves the most relevant supporting
material and routes the section to the right writer: prose, tables, cost models, or
charts.

**Stage 4 — Assurance.** It checks the assembled draft — do the figures reconcile, is
every requirement covered, is every claim supported, is there any overclaiming — and
**re-drafts any failing section automatically**, feeding the failure reason back in, up
to twice, before handing it to a human.

### The one idea that matters most

**A language model is used for judgement and writing; ordinary code is used for anything
that can be checked.** Roughly 40% of the system runs with no AI at all — the cost
modelling, the arithmetic checking, the compliance verification, the bid-decision model,
and the boilerplate. This is deliberate: a language model asked whether a column of
figures adds up will usually say yes, so the app does the addition itself. This split is
what makes the app's claims trustworthy rather than merely fluent.

### Two behaviours worth understanding

- **Gaps are never written around.** If the evidence library has nothing to support a
  requirement, the app will not invent a claim to fill the space. It carves the
  requirement out of the draft, marks it visibly, and raises a task. This is a feature,
  not a limitation — an unevidenced claim is exactly what fails due diligence.

- **Compliance, legal and unevidenced requirements go to a human.** These are carved out
  of the draft before any AI writes a word, because they are the parts a firm cannot
  afford to get wrong automatically.

---

## What the numbers mean

The app reports two automation figures, and the difference between them is the honest
part of the story:

- **Sentence-level automation (~64%):** the share of sentences produced with no human
  input. This is what the app actually saves you.
- **Section-level automation (0%):** a section only counts as automated if *no* sentence
  in it needed a human. Because nearly every section carries at least one carved-out gap,
  this figure is often zero — and that is correct, not a bug. A section needing one human
  sentence is a section someone must open.

Reporting both, rather than just the flattering one, is the point: the app is designed to
be honest about what it did and did not do.

Other measured results (on the development data): **100% of mandatory requirements
extracted**, **98% retrieval accuracy**, **every injected error caught** (a wrong total,
a duration mismatch, a fabricated statistic, an overclaim), and an end-to-end run in about
**126 seconds**.

---

## The technology, briefly

- **Web interface:** Streamlit (a Python web-app framework).
- **Language models:** free-tier cloud APIs (Groq, Gemini, HuggingFace), pooled so that
  if one is rate-limited the next takes over. The app also runs fully offline on a local
  model, just more slowly.
- **Search:** a local hybrid search over 247 chunks of company knowledge and 120 past
  question-answer pairs — keyword search and meaning-based search combined, then re-ranked
  for relevance.
- **Everything runs at zero cost:** the only thing you need to supply is a free API key.

---

## Honest limitations

Stated plainly, because a tool you can trust is one that tells you what it cannot do:

- **It does not win the bid for you.** It produces a strong, traceable first draft. The
  win themes, the client relationship, and the pricing call remain human work.
- **It is only as good as the knowledge library behind it.** A firm with no organised
  past answers gets little from it — the search has nothing to find.
- **The draft is not submission-ready.** It is a starting point that turns days of
  drafting into an afternoon of review. The compliance matrix and the gap list are
  arguably worth more than the prose.
- **It is tuned to one domain** (the sample data is fintech/consulting). Pointed at a
  very different industry, the retrieved evidence would be less relevant.

---

## Running it yourself

```powershell
# one-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env         # then add one free API key

# build the search index (once)
python -m src.ingestion.ingest
python -m src.ingestion.calibrate

# launch the app
streamlit run app/dashboard.py
```

Or use the command-line version for a single run:
```powershell
python -m src.orchestrator "data/incoming/RFP-A_questionnaire_nbfc.md"
```

---

## The one-line summary

> RFP Copilot turns an RFP into a traceable first-draft response — with every claim
> sourced, every number checked, and every gap flagged — so a team responds to more of
> the right bids, with the risky parts visible before the deadline instead of after.
