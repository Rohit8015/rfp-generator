# Reference output — evaluation only

`XCD_RFP_Response.pdf` is the gold-standard response to `data/incoming/RFP Assignment 5.pdf`.

It is the TARGET the pipeline is trying to produce. It must NEVER be ingested into the
retrieval corpus (Chroma or BM25). If it were, the retriever would return the answer
verbatim, `reuse_decision` would collapse to REUSE, and the automation rate — the
project's governing metric — would be meaningless.

Ingestion reads knowledge_base/, historical_rfps/, proof_library/ and templates/.
It must never read data/eval/.

Use this file only to:
- score generated output against a human-written reference
- derive the labelled eval sets (requirements, deliverable forms, compliance matrix)
