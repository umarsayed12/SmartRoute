"""Verify fixed provider URLs, native request formats, usage accounting, and redacted errors."""

import json

import httpx
import pytest

from app.hosted import providers


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("temperature", [0.2, 2.0, None])
async def test_provider_contracts(provider: str, temperature: float | None) -> None:
    """Preserve text and usage while translating system prompts for native Anthropic."""
    def handle(request: httpx.Request) -> httpx.Response:
        """Validate the fixed destination and protocol-specific payload."""
        payload = json.loads(request.content)
        assert payload["model"] == "test-model" and payload["stream"] is False
        if temperature is None:
            assert "temperature" not in payload
        else:
            assert payload["temperature"] == (min(temperature, 1.0) if provider == "anthropic" else temperature)
        if provider == "openai":
            assert str(request.url) == "https://api.openai.com/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer synthetic-key"
            assert payload["max_completion_tokens"] == 100
            assert payload["messages"][0]["role"] == "system"
            return httpx.Response(200, json={"model": "test-model-version", "choices": [{"message": {"content": "Answer"}, "finish_reason": "length"}], "usage": {"prompt_tokens": 20, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 5}}})
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "synthetic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert payload["system"] == "Be concise."
        assert all(message["role"] != "system" for message in payload["messages"])
        assert payload["max_tokens"] == 100
        return httpx.Response(200, json={"model": "test-model-version", "content": [{"type": "thinking", "thinking": "not final text"}, {"type": "text", "text": "Answer"}], "stop_reason": "max_tokens", "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 5, "output_tokens": 8}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await providers.chat(client, provider, "test-model", "synthetic-key", [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Hello"}], temperature, 100)
    assert result.content == "Answer"
    assert result.prompt_tokens == 20 and result.completion_tokens == 8
    assert result.model == "test-model-version" and result.finish_reason == "length"
    assert result.usage_details


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "code"), [("redirect", "provider_rejected"), ("forbidden", "provider_rejected"), ("timeout", "provider_timeout"), ("missing_usage", "invalid_provider_response")])
async def test_provider_failures_are_redacted(kind: str, code: str) -> None:
    """Do not follow redirects, retry calls, or expose provider response bodies."""
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Simulate failed provider responses without external network access."""
        calls.append(str(request.url))
        if kind == "timeout":
            raise httpx.ReadTimeout("private detail", request=request)
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        if kind == "forbidden":
            return httpx.Response(401, json={"error": "private secret detail"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Answer"}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(providers.ProviderFailure) as caught:
            await providers.chat(client, "openai", "test-model", "synthetic-key", [{"role": "user", "content": "Hello"}], 0.2, 100)
    assert caught.value.code == code
    assert "private" not in str(caught.value) and "synthetic-key" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_model_probe_cannot_change_origin() -> None:
    """Encode model identifiers only as path data under a server-controlled origin."""
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Record the probe destination and return a model metadata response."""
        calls.append(request.url)
        return httpx.Response(200, json={"id": "https://other.example/model"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await providers.reachable(client, "openai", "https://other.example/model", "synthetic-key")
    assert calls[0].host == "api.openai.com"


@pytest.mark.asyncio
async def test_temperature_can_be_omitted() -> None:
    """Models that reject custom temperature can use the provider's default explicitly."""
    def handle(request: httpx.Request) -> httpx.Response:
        """Require the compatibility option to affect the actual HTTP payload."""
        assert "temperature" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Answer"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await providers.chat(client, "openai", "test-model", "synthetic-key", [{"role": "user", "content": "Hi"}], None, 100)