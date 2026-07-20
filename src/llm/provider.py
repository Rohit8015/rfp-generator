"""LLM provider wrapper — Phase 2.

Contract:
    generate(prompt: str, tier: Literal["cheap", "strong"], json_schema=None) -> str | dict
    embed(texts: list[str]) -> list[list[float]]
    rerank(query: str, docs: list[str]) -> list[tuple[int, float]]

Ollama is the default and the only provider any acceptance test may require. Cloud
providers sit behind this same interface as optional accelerators. Invalid JSON is
reparsed once before raising. No other module in the codebase may call a model.
"""
