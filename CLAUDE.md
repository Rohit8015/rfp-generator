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

## Zero-cost constraint
- The full pipeline must run with Ollama only. No acceptance test may require a cloud API key.
- Cloud providers are optional accelerators behind the same wrapper interface.

## Safety and integrity rules
- Never invent a proof point to fill a GAP. GAPs surface to a human.
- Compliance, Legal, and all GAP requirements route to STAKEHOLDER — never LLM-drafted as final.
- Never auto-send email. Never auto-submit a response. Drafts only.
- Never hardcode retrieval thresholds; read them from the calibration output in config.
- Keep secrets in .env. Never commit keys or client data.

## Output discipline
- Prefer small, reviewable diffs.
- Log timings and token counts per agent into the runs table.
