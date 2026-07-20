# RFP Copilot v2 — Dataset Next Steps

## 📦 What's in This Package

This package contains the complete synthetic dataset for RFP Copilot v2 — an AI-powered RFP response automation system.

**Contents:**
- 3 Incoming RFPs (A, B, C) for development
- 2 Held-Out Test RFPs (D, E) — DO NOT OPEN DURING DEVELOPMENT
- 120 Historical Q&A pairs
- 10 Knowledge Base documents
- 20 Proof points
- 5 Templates
- 3 Parameter files
- 6 Labelled evaluation sets
- 6 Adversarial documents (for testing)
- 2 Golden reference outputs

**Domain Coverage:** Financial Services, Healthcare, Government, Technology

---

## 🚨 CRITICAL: The Split Configuration

**YOU MUST DO THIS BEFORE USING THE DATASET**

The dataset needs to be split into **dev (60%)** and **test (40%)** sets. **Split on document boundaries** — not on individual items.

### Why This Matters

If you split individual questions, near-duplicate questions leak across dev/test and inflate every metric you report. **Split by entire documents.**

### The Split Rule

| Set | Documents | Count |
|-----|-----------|-------|
| **Dev** | RFP-A, RFP-B, RFP-C | 3 (60%) |
| **Test** | RFP-D, RFP-E | 2 (40%) |

---

## Step 1: Create the Split File

Create one file: **`split.json`** in the root folder (or `data/eval/split.json`)

### Sample `split.json`

```json
{
  "split_name": "RFP_Copilot_v2_Dev_Test_Split",
  "created_date": "2026-07-20",
  "split_strategy": "BY_DOCUMENT",
  "dev_ratio": 0.60,
  "test_ratio": 0.40,
  
  "dev_documents": [
    "RFP-A_Questionnaire",
    "RFP-B_Narrative", 
    "RFP-C_Hybrid"
  ],
  
  "test_documents": [
    "RFP-D_Test_HeldOut",
    "RFP-E_Test_HeldOut"
  ],
  
  "dev_count": 3,
  "test_count": 2,
  
  "notes": "RFP-D and RFP-E are sealed and MUST NOT be used for development or prompt tuning. They are for final evaluation only.",
  
  "hashes": {
    "RFP-D": "REPLACE_WITH_ACTUAL_HASH",
    "RFP-E": "REPLACE_WITH_ACTUAL_HASH"
  }
}
```

### How to Get File Hashes

```bash
# On Linux/Mac
shasum -a 256 RFP-D_Test_HeldOut.md
shasum -a 256 RFP-E_Test_HeldOut.md

# On Windows (PowerShell)
Get-FileHash RFP-D_Test_HeldOut.md -Algorithm SHA256
Get-FileHash RFP-E_Test_HeldOut.md -Algorithm SHA256
```

---

## Step 2: Seal Test Documents

**Rule:** RFP-D and RFP-E are **SEALED**. Do NOT open them during development.

- ✅ Record their hashes in `split.json`
- ✅ Store them securely
- ❌ DO NOT read, analyze, or use them for prompt tuning
- ❌ DO NOT use them for any development activity

**What if you must open them?**
- Document the reason and date
- Note the contamination in your evaluation
- Treat subsequent metrics as "contaminated"

---

## Step 3: Review Assets (Recommended)

**Before building the system, review these items:**

| Asset | File | Priority |
|-------|------|----------|
| Historical Q&A (120) | `historical_qa_120_records.json` | HIGH |
| Knowledge Base docs | `knowledge_base/*.md` | MEDIUM |
| RFP-A, B, C | `incoming/RFP-*.md` | HIGH |
| Templates | `templates/*.md` | LOW |
| Parameter files | `params/*.yaml` | LOW |

**What to check:**
- Are Q&A pairs realistic for your context?
- Do RFPs match your typical client profiles?
- Are knowledge base documents accurate?
- Do parameter rates match your actual billing?

**To customize:**
- Edit company name and details in templates
- Adjust rates in `params/*.yaml` to match your billing
- Modify knowledge base docs to reflect actual capabilities
- Add/remove proof points as needed

---

## Step 4: Inter-Rater Agreement (For Valid Metrics)

**Have a second person label 30 requirement items from `requirements_labelled.json`**

### Process

1. Take 30 random requirements from `requirements_labelled.json`
2. Have second reader independently label:
   - `req_type` (SHALL_REQUIREMENT, SHOULD_REQUIREMENT, MAY_REQUIREMENT)
   - `priority` (MANDATORY, WEIGHTED, NICE_TO_HAVE)
   - `deliverable_form` (PLATFORM, SYSTEM, AI_MODEL, etc.)
3. Compute agreement percentage

**Target:** Agreement ≥ 75% (0.75)

**If agreement is below 75%:**
- Review the label definitions
- Clarify ambiguous cases
- Re-label the 30 items together
- Recompute agreement

---

## Step 5: Threshold Calibration (For Retrieval)

**Use `calibration_pairs.json` to set similarity thresholds**

### Process

1. Compute similarity scores between questions and historical answers
2. Plot the distribution
3. Set thresholds based on percentiles:

| Decision | Suggested Threshold |
|----------|-------------------|
| **REUSE** | 97th percentile |
| **ADAPT** | 85th percentile |
| **SYNTHESIZE** | Below 85th percentile |

**Example:**
- Similarity > 0.85 → REUSE
- Similarity 0.65 – 0.85 → ADAPT
- Similarity < 0.65 → SYNTHESIZE

**Note:** These thresholds should be tuned based on your actual data distribution.

---

## Step 6: Run Retrieval Evaluations

**Use `retrieval_pairs.json` to evaluate retrieval performance**

### Metrics to Compute

| Metric | Description | Target |
|--------|-------------|--------|
| **Recall@1** | Relevant document in top 1 | > 60% |
| **Recall@5** | Relevant document in top 5 | > 85% |
| **MRR** | Mean Reciprocal Rank | > 0.70 |
| **nDCG@5** | Normalized Discounted Cumulative Gain | > 0.75 |

### Compare Approaches

| Approach | Expected Result |
|----------|-----------------|
| **Dense-only** | Baseline |
| **Hybrid (Dense + BM25)** | Better on lexical terms |
| **Hybrid + Rerank** | Best overall |

**Key:** The 10 lexical-dependent items should prove BM25's value over dense-only.

---

## Step 7: Test Adversarial Documents

**6 adversarial documents, each with ONE defect:**

| File | Defect | What Should Catch It |
|------|--------|---------------------|
| `adv_arithmetic.md` | Cost components sum to wrong total | A10 - Checker |
| `adv_duration.md` | Phase durations sum to 34 months, stated 30 | A10 - Checker |
| `adv_entity.md` | FTE peak stated as 24, 31, and 30 | A10 - Checker |
| `adv_missing_section.md` | Required section deleted | A11 - Validator |
| `adv_fabrication.md` | Fabricated statistic with no source | A12 - Grounding |
| `adv_overclaim.md` | "100% uptime, unlimited liability" | A13 - Detector |

**Test them one at a time. Each should be caught by the appropriate component.**

---

## Step 8: Grounding Checker Evaluation

**Use `grounding_labelled.json` to test the grounding checker**

### Statistics

| Metric | Description |
|--------|-------------|
| **Precision** | Of claims flagged, how many were actually unsupported? |
| **Recall** | Of unsupported claims, how many were flagged? |
| **False Positive Rate** | How often does it flag supported claims? |

**Target:**
- Precision > 0.80
- Recall > 0.80
- False Positive Rate < 0.10

**Important:** False Positive Rate matters most — a checker that flags everything is useless.

---

## Step 9: Deal Context Evaluation

**Use `deal_contexts.json` to test bid/no-bid decisions**

### Scenarios

| Scenario | Expected Decision |
|----------|------------------|
| DC-001 | BID |
| DC-002 | BID |
| DC-003 | BID |
| DC-004 | NO_BID |
| DC-005 | BID |
| DC-006 | PARTNER_BID |

### Evaluation

- Does the system correctly classify each scenario?
- Does it provide appropriate confidence?
- For borderline cases, does it recommend partnering?

---

## Step 10: Golden Output Comparison (Phase 12)

**Use `golden/*.md` as reference outputs for RFP-D and RFP-E**

### Scoring Rubric (1-5 scale)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Requirement Coverage | 25% | Did it address all requirements? |
| Factual Groundedness | 25% | Are claims supported by corpus? |
| Narrative Coherence | 15% | Does it flow logically? |
| Buyer-Specificity | 15% | Would a competitor have sent the same? |
| Professional Presentation | 10% | Is it well-structured? |
| Effort-to-Usable | 10% | How many edits to submission-ready? |

### Process

1. Generate system output for RFP-D and RFP-E
2. Compare to golden outputs
3. Two independent readers score (1-5 each)
4. Average scores across readers
5. Document qualitative feedback

---

## 📋 Complete Readiness Checklist

### ✅ ALREADY DONE (Data Generated)

- [x] RFP-A, RFP-B, RFP-C written
- [x] RFP-D, RFP-E written (sealed)
- [x] 120 historical Q&A pairs
- [x] 10 knowledge base docs
- [x] 20 proof points
- [x] 5 templates
- [x] 3 parameter files
- [x] Requirements labelled (33 items)
- [x] Classification labelled (60 items)
- [x] Retrieval pairs (50 items)
- [x] Calibration pairs (200 items)
- [x] Deal contexts (6 scenarios)
- [x] Grounding pairs (40 items)
- [x] Adversarial docs (6 items)
- [x] Golden outputs (2 items)

### ⏳ YOU NEED TO DO

- [ ] Create `split.json` (see Step 1)
- [ ] Record hashes of RFP-D and RFP-E
- [ ] Seal test documents (DO NOT OPEN)
- [ ] Review assets for quality/accuracy
- [ ] Inter-rater agreement (≥0.75)
- [ ] Set similarity thresholds
- [ ] Run retrieval evaluations
- [ ] Test adversarial documents
- [ ] Evaluate grounding checker
- [ ] Compare golden outputs

---

## 🚫 Data Hygiene Rules

| DO | DON'T |
|----|-------|
| ✅ Split on document boundaries | ❌ Split individual items |
| ✅ Seal test documents | ❌ Open test documents |
| ✅ Record file hashes | ❌ Modify test documents |
| ✅ Review assets before use | ❌ Trust data blindly |
| ✅ Use human labelling | ❌ LLM-label requirements |
| ✅ Validate JSON files | ❌ Skip validation |

---

## 📝 Quick Reference: File Locations

```
/
├── split.json                                 ← YOU CREATE THIS
├── RFP-A_Questionnaire.md                     ← Dev
├── RFP-B_Narrative.md                         ← Dev
├── RFP-C_Hybrid.md                            ← Dev
├── RFP-D_Test_HeldOut.md                      ← TEST (SEALED)
├── RFP-E_Test_HeldOut.md                      ← TEST (SEALED)
├── historical_qa_120_records.json
├── knowledge_base/
│   ├── KB-001_Company_Overview.md
│   ├── KB-002_Security_Policy.md
│   └── ... (10 files total)
├── proof_points.json
├── templates/
│   ├── template_cover_page.md
│   ├── template_about_us.md
│   └── ... (5 files total)
├── params/
│   ├── programme_small.yaml
│   ├── programme_standard.yaml
│   └── programme_large.yaml
├── eval/
│   ├── requirements_labelled.json
│   ├── classification_labelled.csv
│   ├── retrieval_pairs.json
│   ├── calibration_pairs.json
│   ├── deal_contexts.json
│   ├── grounding_labelled.json
│   ├── adversarial/
│   │   ├── adv_arithmetic.md
│   │   ├── adv_duration.md
│   │   ├── adv_entity.md
│   │   ├── adv_missing_section.md
│   │   ├── adv_fabrication.md
│   │   └── adv_overclaim.md
│   └── golden/
│       ├── rfp_d_golden.md
│       └── rfp_e_golden.md
└── README_NEXT_STEPS.md                      ← THIS FILE
```

---

## ✅ Next Steps Summary

1. **Create `split.json`** using the sample above
2. **Record hashes** for RFP-D and RFP-E
3. **Seal test documents** (RFP-D, RFP-E) — DO NOT OPEN
4. **Review assets** for quality
5. **Proceed to system build** (Phase 3)

**The dataset is now ready for use!**

---

*Generated: July 20, 2026 | Version: 1.0.0*

---

## ❓ Questions?

If you have questions about the dataset or next steps:

1. **Read this document carefully** (most questions are covered)
2. **Check the sample `split.json`** (Step 1 has what you need)
3. **Review the asset files** (they follow the RFP Copilot v2 spec)
4. **For data quality issues**: The data is synthetic; customize as needed for your context

**Note:** RFP-D and RFP-E are the **ONLY** files you should not touch during development. Everything else is open for review and customization.