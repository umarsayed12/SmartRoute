"""Call an OpenAI-compatible chat endpoint without depending on its SDK."""

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
    api_key: str | None = None,
) -> ProviderResult:
    """Generate a remote reply using an API root or a URL ending in /v1."""
    api_root = (base_url or settings.LARGE_BASE_URL).rstrip("/")
    if not api_root:
        raise ValueError("Set LARGE_BASE_URL or pass base_url to use this provider.")
    if not api_root.endswith("/v1"):
        api_root += "/v1"
    key = settings.LARGE_API_KEY.get_secret_value() if api_key is None else api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    started = perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        response = await client.post(
            f"{api_root}/chat/completions", json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    usage = data.get("usage") or {}
    return ProviderResult(
        content=data["choices"][0]["message"]["content"],
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        latency_ms=round((perf_counter() - started) * 1000),
        model=data.get("model", model),
    )