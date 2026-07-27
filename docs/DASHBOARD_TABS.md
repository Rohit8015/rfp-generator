# RFP Copilot — The Dashboard, Tab by Tab

A detailed walkthrough of every tab in the web application: what each part is, where its
data comes from, how to read it, and the subtleties worth knowing. Grounded in the actual
UI code (`app/dashboard.py`).

The through-line: **Decide** (should we bid + what we can't prove) → **Requirements**
(what was asked) → **Draft** (the answer, attributed) → **Compliance** (is everything
covered) → **Assurance** (did it pass its own checks) → **Tasks** (what humans must do) →
**Export** (deliver it). Each tab answers one question a bid manager would otherwise
answer by hand.

---

## Before the tabs: the sidebar and the run

You pick or upload an RFP in the sidebar, choose whether to **Use models** (off runs the
deterministic path only), and click **Run pipeline**. A per-stage progress bar shows the
thirteen agents working — in execution order, with readable stage names — for roughly two
minutes. When it finishes, a four-metric header appears above the tabs: **sections clean**,
**sentences automated**, **coverage**, and **evidence gaps**, with a line breaking the
sections into clean / drafted-with-carve-outs / escalated.

---

## Tab 1 · Decide

The first tab on purpose. The most valuable decision is whether to bid at all, and knowing
your evidence gaps upfront changes how you pursue the deal. Two halves.

### Half 1 — "Should we bid?" (interactive)

Unlike every other tab, this half **re-computes as you drag** — it is a what-if tool, not
a fixed pipeline output.

**Six inputs** describe the commercial situation of this pursuit:

- **Solution fit %** (0–100) — how well your capabilities match the requirements.
- **Relationship** (DEEP / MODERATE / LIMITED / NEW) — depth of the client relationship.
- **Incumbent strength** (NONE / WEAK / MEDIUM / STRONG) — how entrenched the existing
  supplier is.
- **Entry timing** (EARLY / MID / LATE) — how early you got into the deal.
- **Competitors** (1–10) — size of the field.
- **Deal size vs normal** (0.3–2.0×) — this deal relative to your typical one.

**The verdict** — a colour-coded banner with the win probability:

| Verdict | Colour | Meaning |
|---|---|---|
| BID | green | pursue it |
| PARTNER_BID | amber | pursue, but partner to compete |
| NO_BID | red | walk away |

**The driving factors** — a bullet list naming *why* (e.g. "late entry against an
entrenched incumbent", "deal size 0.5× normal indicates severe price compression"). This
is what makes the recommendation defensible rather than a black-box number.

**The model behind it** — a deterministic weighted blend: fit 0.35, relationship 0.20,
incumbency 0.20, timing 0.15, competition 0.10, mapped to a win probability capped at 85%,
plus two hard rules: late entry against a STRONG incumbent applies a 0.35× penalty, and a
deal size ≤ 0.6× routes to PARTNER_BID. Win probability below 20%, or fit below 50%, forces
NO_BID.

*Best demo beat:* drag Entry timing to LATE and Incumbent to STRONG — BID flips to NO_BID
with the reason appearing live.

### Half 2 — "What we cannot prove" (computed)

Not interactive — this is the actual output of the run's proof matcher. Either a green
"Every requirement has supporting evidence", or an amber warning with the **count of
gaps** and the key sentence — *"the system will not write around these; they are carved
out of the draft and routed to a human"* — followed by a table of every GAP requirement:
ID, priority, full text, and the matcher's rationale.

### The subtlety

The two halves answer different questions and don't feed each other. The **sliders are
manual** because the RFP doesn't state your relationship, the incumbent or the deal size —
the qualifier can't read those from the document. The **gap list is computed** from the
RFP. On this tab you combine your commercial judgement (sliders) with the system's evidence
analysis (gaps) to make the bid call.

---

## Tab 2 · Requirements

The backbone — every requirement A2 extracted, with everything the downstream agents
decided about each. A single table plus a summary line.

**Eight columns:**

| Column | What it is | From |
|---|---|---|
| ID | stable identifier `R-001`… | A2 |
| Priority | MANDATORY / WEIGHTED / NICE_TO_HAVE | A2 (Shipley cue words) |
| Type | one of six requirement types | A2 |
| Renders as | the deliverable form (PROSE, TABLE, COSTING…) — **routes the writer** | A2 |
| Evidence | 🟢 STRONG / 🟠 PARTIAL / 🔴 GAP | A7 proof matcher |
| Section | which outline section answers it | A6 architect |
| Requirement | the full text | extracted |
| Found by | `cue` / `llm` / `both` | which extraction pass caught it |

**How to read it** — three reads, in order of value:

1. **MANDATORY + 🔴 GAP** — a must-win item you can't evidence; your biggest risk. Scan
   for red on high-priority rows first.
2. **Evidence spread** — a table dominated by 🔴 means the knowledge library doesn't cover
   this RFP's domain well.
3. **Mandatory count** (in the summary line) — the number of pass/fail items you must
   satisfy or be disqualified.

**Two things to know:**
- Status columns are pinned narrow and the requirement-text column absorbs the slack, so
  Evidence and Section stay readable (they used to clip to "PAR…").
- The table can hold **more rows than the RFP has numbered requirements**, because A2 also
  extracts *implied* deliverables and gates for recall over precision (~100% mandatory
  recall at ~65% precision). Near-duplicate or soft "implied" rows are the deliberate
  trade, visible in the `Found by` column.

---

## Tab 3 · Draft

The proposal itself. Every sentence colour-coded by where it came from; sections editable.

**1 · The caption** — states what the tab does: colour = provenance, edits persist.

**2 · The Provenance legend expander** — a collapsible key to all six provenance kinds:

| Pill | Meaning |
|---|---|
| REUSED (green) | lifted from an approved past answer |
| ADAPTED (blue) | a past answer reworked for this buyer |
| SYNTHESIZED (amber) | written from several sources |
| TEMPLATE (grey) | boilerplate, no model involved |
| COMPUTED (purple) | arithmetic, no model involved |
| STAKEHOLDER (red) | a human must write this |

**3 · One expander per section.** The header encodes three things:
- **Status icon** — 🟢 drafted, or 🔴 escalated (a section a human must own entirely).
- **Title · form** — e.g. "Response to section 2.1 · PROSE".
- **Redraft count** — "· 2 redraft(s)" appears only if the self-healing loop had to
  re-draft it; its absence means it passed assurance first time.

Inside each expander, four elements:

- **Provenance-mix caption** — a tally like `ADAPTED 6 · STAKEHOLDER 3 · SYNTHESIZED 2`, so
  you can see a section's composition before reading a word.
- **The highlighted body** — text with every prose sentence wrapped in its provenance
  colour; hover for the kind and source IDs. Markdown structure (headings, tables, bullets)
  is left uncoloured so it still renders correctly. The red carve-out block near the end —
  *"Requires input before submission…"* — is STAKEHOLDER-coloured and lists the carved-out
  requirements.
- **Charts** — visual sections (GANTT, COSTING) show their rendered images inline.
- **Edit box + Save** — overwrites the section's content in the current run, stores the
  edit, and confirms *"Saved. Re-export to include this edit."*

**The subtlety:** editing changes the *content* but does **not** re-run provenance or
assurance on your text — your edit is a manual override that flows into the exported
document but the highlighting won't update until a fresh run.

---

## Tab 4 · Compliance

The auditor's view — proof that every requirement is answered, and where. Built by A11
deterministically.

**Coverage metric** — a single number, e.g. "Coverage 100.0%", the share of requirements
traced to **drafted** content. The caption states the nuance: *measured against what was
written, not planned* — an escalated, undrafted section reduces coverage.

**The matrix table** — one row per requirement: RAG colour, ID, priority, the section that
answers it, the **paragraph anchor** (e.g. `S-03#p2` — traceability down to the paragraph),
and the text.

### How a colour is assigned

1. Find the section planned to answer the requirement.
2. Was it actually **drafted** (not escalated)?
3. If drafted, measure how strongly its best paragraph addresses it (share of the
   requirement's meaningful words present, `ADDRESSED_FLOOR = 0.30`).

| Colour | Condition | Meaning |
|---|---|---|
| 🟢 GREEN | drafted and overlap ≥ 0.30 | substantively answered |
| 🟠 AMBER | drafted but overlap < 0.30 | written in the right place, but thin |
| 🔴 RED | planned section not drafted | not addressed at all |

### What happens to AMBER

Amber **counts as covered** (coverage = GREEN + AMBER; only RED is uncovered). Downstream
it does exactly one thing: an **INFO** assurance finding — *"assigned to S-03 but the
drafted text only weakly addresses it"* — surfaced on the Assurance tab. It does **not**
trigger a redraft and does **not** raise a task. It's an advisory nudge: "a human may
strengthen this paragraph." Because strength is a token-overlap judgement, amber is best
read as "worth a glance", not "definitely inadequate" — which is why it's only INFO.

### What happens to RED

Red is the serious one — the section was never drafted (usually escalated by the guardrail).
It gets handled three ways:
1. **Reduces coverage** — the only colour that drags the percentage down.
2. **Becomes a graded finding** — MANDATORY red → 🛑 **BLOCKER** (a submit-blocker, shown
   at the top of Assurance); non-mandatory → ⚠️ WARN.
3. **Already has an owned task** — because the section was escalated, W1 created a
   department-routed, dated task, so it appears on the Tasks tab.

So the same red mandatory requirement surfaces three ways — 🔴 here, 🛑 on Assurance, and an
owned task on Tasks — so it can't be missed. The rule of thumb: **amber = "written but
weak" → nudge; red = "not written" → coverage hit + finding + task.**

---

## Tab 5 · Assurance

The self-check — did the document pass its own gates? Two parts.

**Part 1 — Consistency result.** A banner:
- Green: *"No contradictions across 35 extracted facts."* The fact count proves the numbers
  were actually examined.
- Red: each contradiction with its kind (TABLE_TOTAL, DURATION, ENTITY_VALUE, PERCENTAGE),
  the section(s) it's localized to, and the detail (e.g. "components sum to 41.95 but total
  states 38.25"). This is the deterministic arithmetic checker.

**Part 2 — Findings table**, sorted by severity:

| Column | Meaning |
|---|---|
| icon | 🛑 BLOCKER · ⚠️ WARN · ℹ️ INFO |
| Severity | the level |
| Type | CONTRADICTION, UNCOVERED_REQ, UNGROUNDED, RISK_LANGUAGE, VOICE_DRIFT |
| Section | where it occurs |
| Detail | the specific problem |
| Evidence | the offending snippet |

**How to read it:** 🛑 blockers at the top must be resolved before submission (unbounded
liability, a missed mandatory requirement, an arithmetic contradiction). ⚠️ warnings (e.g.
UNGROUNDED claims) are review flags, not stoppers. ℹ️ info (e.g. VOICE_DRIFT, weak
coverage) is polish. Note UNGROUNDED findings are **advisory** — flagged here but they did
*not* trigger a redraft, by design, so a grounding flag means "a human should check this
claim", not "the system failed".

---

## Tab 6 · Tasks

The human hand-off — everything the system deliberately would not do on its own.

Either a green "No human tasks raised", or a table:

| Column | Meaning |
|---|---|
| Task | ID |
| Title | e.g. "Evidence gap: R-013" or "Author section: Legal" |
| Owner | routed department — Legal, Compliance, Information Security, Commercial, Resourcing, Solution Architecture, Client Development, or Bid Management |
| Priority | inherited from the requirement |
| Due | worked back from the deadline (mandatory −7 days, weighted −4, nice-to-have −2) |
| Covers | which requirement IDs this task addresses |

This turns the evidence gaps and compliance/legal carve-outs into an owned, dated
work-list. Every red carve-out from the Draft tab appears here with a named department —
what makes the hand-off real rather than a note in the margin.

---

## Tab 7 · Export

The delivery point — three parts.

**1 · Download buttons** — three files:
- **Proposal (Markdown)** — the raw document.
- **Proposal (docx)** — Word, with rendered tables, embedded charts, the compliance
  matrix, **the Human tasks table, and the blocking-findings list**. The submittable
  artefact, now self-contained.
- **Automation report** — the headline metrics, provenance breakdown, GAP list, consistency
  status, and the explicit per-section status list.

If you edited a section on the Draft tab, the downloads reflect it.

**2 · "Where the text came from"** — a labelled progress bar for each of the six provenance
kinds (listed even at zero, so it matches the legend), showing sentence counts and shares.
A high STAKEHOLDER share means a lot needed a human; a high REUSED/ADAPTED share means the
corpus carried the load.

**3 · Provider usage** — a JSON block: calls per provider, token totals, cache hits,
latency. The evidence for "provider mix is a reportable metric".

---

## Where to find a section's status

- **Draft tab** — the header icon (🔴 escalated, 🟢 otherwise) and the redraft count.
- **Draft tab body** — an escalated section reads *"This section requires human authorship
  and has not been drafted. Reason: …"*.
- **Automation report** — lists each non-automated section explicitly as, e.g.,
  `S-05 Legal (ESCALATED)`.

A normal run produces only **DRAFTED** and **ESCALATED**. `APPROVED` is a defined status
reserved for a human-sign-off step that isn't wired into the current pipeline, so you won't
see it from a fresh run.

---

## How a human finds their work in the exported document

Search the exported proposal for:
1. **"Requires input"** — jumps to every carve-out block inside a drafted section.
2. **"human authorship"** — jumps to every fully-escalated section.
3. **"## Human tasks"** (Markdown) or the **Human tasks** heading (docx) — the consolidated
   checklist with owners and due dates.

Between those three, you'll have hit every human-required spot in the document.
