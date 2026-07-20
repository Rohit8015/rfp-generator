# Retrieval threshold calibration

- **Version:** `2026-07-21-bge-small-en-v1.5`
- **Embedding model:** `BAAI/bge-small-en-v1.5` (local, 384-dim)
- **Method:** unsupervised percentile calibration on corpus self-similarity; REUSE at p99.5, ADAPT at p97.0
- **Background pairs:** 7,140

## Derived thresholds

| Decision | Condition |
|---|---|
| REUSE | top-1 similarity >= **0.7972** |
| ADAPT | **0.741** <= similarity < **0.7972** |
| SYNTHESIZE | similarity < **0.741** |
| STAKEHOLDER | Not score-derived. Forced by the Compliance/Legal/GAP guardrail regardless of similarity. |

## Method

Every pair of historical questions is scored against every other, giving the
distribution of *two questions that merely share a corpus*. Thresholds sit at
high percentiles of that distribution: to be called REUSE, a match must be
more similar than 99.5% of unrelated pairs.

This is unsupervised. It needs no labelled relations, which matters because
the labels shipped with this dataset do not hold up (see below).

## Background distribution

| n | min | median | p90 | p97 | p99.5 | max |
|---|---|---|---|---|---|---|
| 7,140 | 0.4363 | 0.6107 | 0.7 | 0.741 | 0.7972 | 0.9539 |

The REUSE threshold sits **+0.1865** above the median of the
background distribution.

## Diagnostic: the supplied labels

`calibration_pairs.json` ships a `relation` and a `similarity_score` per
pair. **Neither sets any threshold here.** An earlier version of this
module calibrated on them and produced incoherent bands, because the
labels do not correspond to any measurable similarity:

| Labelled relation | Measured median |
|---|---|
| REUSE | 0.9114 |
| ADAPT | 0.8549 |
| SYNTHESIZE | 0.8730 |

SYNTHESIZE scoring at or above ADAPT is the tell. Inspection confirms it:
pairs such as *"How do you ensure GDPR compliance?"* against *"How do you
ensure GDPR compliance for European clients?"* carry the SYNTHESIZE label
while being near-duplicates. The same inversion appears independently in
`retrieval_pairs.json`.

Agreement between the shipped labels and the thresholds derived here: **14/30**. That number measures the labels, not the
thresholds.

**Action required:** the reuse-decision labels need re-labelling by a
human before any REUSE/ADAPT/SYNTHESIZE accuracy figure can be reported.
Retrieval Recall@5 and MRR are unaffected — they depend on `relevant_ids`,
not on `expected_decision`.

| Pair | Shipped label | Derived | Measured | Shipped score | Target |
|---|---|---|---|---|---|
| C-001 | REUSE | REUSE | 0.9844 | 0.97 | HQ-001 |
| C-022 | ADAPT ⚠ | REUSE | 0.9704 | 0.66 | HQ-109 |
| C-010 | REUSE | REUSE | 0.9399 | 0.94 | HQ-005 |
| C-007 | REUSE | REUSE | 0.9397 | 0.94 | HQ-003 |
| C-015 | ADAPT ⚠ | REUSE | 0.9363 | 0.71 | HQ-108 |
| C-029 | SYNTHESIZE ⚠ | REUSE | 0.9359 | 0.44 | HQ-063 |
| C-004 | REUSE | REUSE | 0.9247 | 0.96 | HQ-002 |
| C-025 | SYNTHESIZE ⚠ | REUSE | 0.9245 | 0.45 | HQ-047 |
| C-019 | ADAPT ⚠ | REUSE | 0.9213 | 0.72 | HQ-019 |
| C-006 | REUSE | REUSE | 0.9194 | 0.96 | HQ-003 |
| C-009 | REUSE | REUSE | 0.9189 | 0.96 | HQ-014 |
| C-024 | ADAPT ⚠ | REUSE | 0.9168 | 0.72 | HQ-017 |
| C-030 | SYNTHESIZE ⚠ | REUSE | 0.9129 | 0.41 | HQ-117 |
| C-008 | REUSE | REUSE | 0.9038 | 0.95 | HQ-006 |
| C-011 | REUSE | REUSE | 0.8895 | 0.93 | HQ-032 |
| C-017 | ADAPT ⚠ | REUSE | 0.8861 | 0.73 | HQ-055 |
| C-023 | ADAPT ⚠ | REUSE | 0.8818 | 0.7 | HQ-015 |
| C-005 | REUSE | REUSE | 0.8665 | 0.95 | HQ-002 |
| C-028 | SYNTHESIZE ⚠ | REUSE | 0.8331 | 0.4 | HQ-050 |
| C-020 | ADAPT ⚠ | REUSE | 0.8281 | 0.68 | HQ-106 |
| C-002 | REUSE | REUSE | 0.8077 | 0.94 | HQ-001 |
| C-012 | REUSE | REUSE | 0.803 | 0.95 | HQ-031 |
| C-027 | SYNTHESIZE ⚠ | REUSE | 0.7986 | 0.42 | HQ-023 |
| C-021 | ADAPT | ADAPT | 0.7954 | 0.74 | HQ-024 |
| C-018 | ADAPT | ADAPT | 0.7935 | 0.7 | HQ-011 |
| C-003 | REUSE ⚠ | SYNTHESIZE | 0.729 | 0.93 | HQ-001 |
| C-016 | ADAPT ⚠ | SYNTHESIZE | 0.7207 | 0.69 | HQ-025 |
| C-014 | ADAPT ⚠ | SYNTHESIZE | 0.6807 | 0.68 | HQ-006 |
| C-026 | SYNTHESIZE | SYNTHESIZE | 0.6787 | 0.38 | HQ-003 |
| C-013 | ADAPT ⚠ | SYNTHESIZE | 0.6727 | 0.72 | HQ-001 |
