"""Shared result structure for local and OpenAI-compatible model calls."""

from dataclasses import dataclass


@dataclass
class ProviderResult:
    """Carry generated text, token counts, latency, and the actual model name."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model: str