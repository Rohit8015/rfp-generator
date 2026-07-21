# Three-minute demo script

Live end-to-end run. Rehearse once; the whole thing is about 126 seconds of pipeline
plus talking.

## Before you start

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.ingestion.ingest        # only if db/ is empty
streamlit run app/dashboard.py
```

Check: sidebar shows `groq → gemini → huggingface`. If a provider is down the chain
fails over silently, which is itself worth mentioning if it happens.

Have a terminal open on a second tab with the CLI ready — if the wifi dies mid-demo,
switch to `--offline` and talk about graceful degradation instead. That is a real
feature, not a save.

---

## 0:00 — The problem (20 seconds)

> "A consultancy answers maybe 80 RFPs a year, wins a quarter of them, and spends over a
> hundred hours on each. Most of that effort goes into bids they lose. And the thing that
> disqualifies a bid is usually not bad writing — it is missing one mandatory requirement,
> or a cost table that does not add up."

## 0:20 — Run it (10 seconds, then let it work)

Pick `RFP-A_questionnaire_nbfc.md`, click **Run pipeline**.

While the progress bar moves, name the planes as they appear:

> "Comprehension, strategy, generation, assurance. Thirteen agents. About 40% of it is
> plain Python with no model involved — the costing, the charts, the arithmetic checks."

## 1:00 — Decide tab first (40 seconds)

> "Before it writes anything, it answers the question that saves the most money: should
> we bid at all?"

Move the **Entry timing** slider to `LATE` and **Incumbent** to `STRONG`.

> "Late against an entrenched incumbent — the requirement has already been shaped by
> someone else. It says NO_BID and tells you why. That one call is worth more than
> everything else in the tool."

Scroll to **What we cannot prove**:

> "Twenty-four requirements have no supporting evidence in our library. Multilingual UI,
> AR/VR, social listening — we have never done them. The system will not write around
> these. It carves them out and raises a task."

## 1:40 — Draft tab (50 seconds)

Open any section. Point at the colours.

> "Every sentence is coloured by where it came from. Green is lifted from an approved
> past answer. Blue is adapted. Orange is synthesised from several sources. Grey is
> arithmetic — no model touched it. Red is a human must write this."

Hover a sentence to show the source ID.

> "Nothing here is unattributable. If a client asks where a number came from, you can
> answer in one click."

## 2:30 — Assurance tab (20 seconds)

> "It checks its own work. Cost components against the stated total, phase durations
> against the programme duration, every claim against its cited source, and anything
> that promises 100% uptime or unlimited liability."

If you want the strongest single beat, open `data/eval/adversarial/adv_arithmetic.md`
beforehand and show A10 catching a ₹3.7 crore discrepancy no human would spot at 2am.

## 2:50 — Close (10 seconds)

> "Sixty-six percent of the sentences were produced with no human input. The section-level
> number is zero, because almost every section has one carved-out requirement — and a
> section needing one human sentence is a section someone must open. I report both,
> because the flattering number on its own would be dishonest."

---

## Questions you will get

**"How do you know it isn't making things up?"**
Two answers. Structurally, a sentence cannot exist in the output without a provenance
record, and a record cannot cite a source the retriever never returned. Empirically, the
groundedness checker scores 0.909 precision and 1.000 recall against 40 labelled claims.

**"What is the automation rate really?"**
Zero percent of sections, 65.9% of sentences. The section metric is deliberately
unforgiving. Both are in the report.

**"Why cloud models if the plan said local?"**
Measurement. A local 7B on this machine ran at 0.15 tokens per second — 68 tokens took
452 seconds. The architecture did not change; every call still goes through one provider
interface, and it still runs on Ollama if you set one environment variable.

**"Did you test on data you tuned against?"**
No. RFP-D and RFP-E are sealed, hashed in `data/eval/split.json`, and stored outside the
directories ingestion reads. A test fails if either file changes.

**"What does it get wrong?"**
The proof matcher is the weakest component — there is no ground truth for it in the
dataset, so the boundary between PARTIAL and GAP is set from a threshold sweep rather
than from labels. And the calibration labels shipped with the dataset are demonstrably
wrong: pairs labelled "unrelated" are near-duplicates, which is why threshold calibration
ignores them and derives from the corpus distribution instead.
