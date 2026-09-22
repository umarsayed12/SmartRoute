"""Call fixed OpenAI/Anthropic endpoints and normalize text, usage, and safe failures."""

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx

ROOTS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1"}


class ProviderFailure(RuntimeError):
    """Expose only a stable error category and optional upstream status, never body/credentials."""

    def __init__(self, code: str, status: int | None = None) -> None:
        """Retain safe diagnostics for request history and HTTP translation."""
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class Completion:
    """Carry final text and the provider's complete reported usage categories."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model: str
    finish_reason: str
    usage_details: dict[str, Any]


def _count(value: Any) -> int:
    """Accept only non-negative integer token counts, including zero."""
    if type(value) is not int or value < 0:
        raise ValueError("Invalid token usage.")
    return value


async def chat(
    client: httpx.AsyncClient, provider: str, model: str, api_key: str,
    messages: list[dict[str, str]], temperature: float | None, max_tokens: int,
) -> Completion:
    """Make one bounded text-generation call without redirects or automatic retries."""
    if provider not in ROOTS:
        raise ProviderFailure("unsupported_provider")
    root = ROOTS[provider]
    if provider == "openai":
        url = f"{root}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_completion_tokens": max_tokens, "stream": False}
    else:
        url = f"{root}/messages"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        payload = {
            "model": model, "messages": [message for message in messages if message["role"] != "system"],
            "temperature": min(temperature, 1.0) if temperature is not None else None, "max_tokens": max_tokens, "stream": False,
        }
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        if system:
            payload["system"] = system
        if not payload["messages"]:
            raise ProviderFailure("invalid_conversation")
    if temperature is None:
        payload.pop("temperature", None)
    started = perf_counter()
    try:
        response = await client.post(url, json=payload, headers=headers, follow_redirects=False, timeout=httpx.Timeout(120, connect=10))
        response.raise_for_status()
        data = response.json()
        usage = data["usage"]
        if provider == "openai":
            content = data["choices"][0]["message"].get("content") or ""
            prompt_tokens = _count(usage["prompt_tokens"])
            completion_tokens = _count(usage["completion_tokens"])
            reason = data["choices"][0].get("finish_reason", "stop")
        else:
            content = "\n".join(block["text"] for block in data["content"] if block.get("type") == "text")
            prompt_tokens = sum(_count(usage.get(name, 0)) for name in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            if "input_tokens" not in usage:
                raise ValueError("Missing input usage.")
            completion_tokens = _count(usage["output_tokens"])
            reason = data.get("stop_reason", "end_turn")
        if not isinstance(content, str) or not isinstance(data.get("model", model), str):
            raise ValueError("Invalid text response.")
        return Completion(
            content, prompt_tokens, completion_tokens, round((perf_counter() - started) * 1000),
            data.get("model", model), "length" if reason in ("length", "max_tokens") else "stop", usage,
        )
    except httpx.TimeoutException:
        raise ProviderFailure("provider_timeout") from None
    except httpx.HTTPStatusError as error:
        raise ProviderFailure("provider_rejected", error.response.status_code) from None
    except httpx.RequestError:
        raise ProviderFailure("provider_unavailable") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ProviderFailure("invalid_provider_response") from None


async def reachable(client: httpx.AsyncClient, provider: str, model: str, api_key: str) -> bool:
    """Probe only the fixed provider's model endpoint without generating tokens."""
    if provider not in ROOTS:
        return False
    headers = {"Authorization": f"Bearer {api_key}"} if provider == "openai" else {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    try:
        response = await client.get(f"{ROOTS[provider]}/models/{quote(model, safe='')}", headers=headers, follow_redirects=False, timeout=5)
        response.raise_for_status()
        return response.json().get("id") == model
    except (httpx.HTTPError, ValueError, AttributeError):
        return False