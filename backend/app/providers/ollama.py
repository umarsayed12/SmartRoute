"""Call Ollama's non-streaming chat API and normalize its response."""

from time import perf_counter

import httpx

from app.config import settings
from app.providers.base import ProviderResult


async def chat(
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int | None = None,
    *,
    base_url: str | None = None,
) -> ProviderResult:
    """Generate an Ollama reply, propagating connection and HTTP errors."""
    options: dict[str, float | int] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    url = f"{(base_url or settings.OLLAMA_BASE_URL).rstrip('/')}/api/chat"
    started = perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    return ProviderResult(
        content=data["message"]["content"],
        prompt_tokens=data.get("prompt_eval_count", 0),
        completion_tokens=data.get("eval_count", 0),
        latency_ms=round((perf_counter() - started) * 1000),
        model=data.get("model", model),
    )