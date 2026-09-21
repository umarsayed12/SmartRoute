"""Verify chat response compatibility, single-tier behavior, and API errors."""

from collections.abc import AsyncIterator
from time import time
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from openai import AsyncOpenAI, BadRequestError

from app.api import chat
from app.config import Settings
from app.main import app
from app.providers.base import ProviderResult


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Use deterministic settings and a stubbed provider without network access."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(chat, "settings", Settings(_env_file=None))
    mocked = AsyncMock(return_value=ProviderResult(
        content="Hello!", prompt_tokens=12, completion_tokens=3,
        latency_ms=17, model="qwen2.5:1.5b",
    ))
    monkeypatch.setattr(chat.ollama, "chat", mocked)
    return mocked


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Call the real ASGI application with an in-process HTTP client."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as connection:
        yield connection


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["smartroute/auto", "smartroute/large", "other-model"])
async def test_chat_response(
    client: httpx.AsyncClient, provider: AsyncMock, model: str
) -> None:
    """Every model name currently uses small and returns the full completion shape."""
    before = int(time())
    response = await client.post("/v1/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    data = response.json()
    assert data["id"].startswith("chatcmpl-")
    assert data["object"] == "chat.completion"
    assert before <= data["created"] <= int(time())
    assert data["model"] == "qwen2.5:1.5b"
    assert data["choices"] == [{
        "index": 0,
        "message": {"role": "assistant", "content": "Hello!"},
        "finish_reason": "stop",
    }]
    assert data["usage"] == {
        "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
    }
    routing = data["smartroute"]
    assert routing["request_id"] == data["id"]
    assert routing["tier_chosen"] == routing["tier_final"] == "small"
    assert routing["escalated"] is False
    assert routing["confidence"] is None
    assert routing["routing_mode"] == "single_tier"
    assert routing["reason"]
    assert routing["latency_ms"] == 17
    assert routing["actual_cost_usd"] == 0
    assert routing["reference_cost_usd"] == pytest.approx(0.00006)
    provider.assert_awaited_once_with(
        model="qwen2.5:1.5b",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.2,
        max_tokens=None,
        base_url="http://localhost:11434",
    )


@pytest.mark.asyncio
async def test_chat_options_and_unique_ids(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Preserve the conversation and generation options across independent calls."""
    messages = [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "How are you?"},
    ]
    payload = {"model": "smartroute/auto", "messages": messages,
               "temperature": 0.7, "max_tokens": 32}
    first = await client.post("/v1/chat/completions", json=payload)
    second = await client.post("/v1/chat/completions", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert provider.await_count == 2
    assert provider.await_args.kwargs["messages"] == messages
    assert provider.await_args.kwargs["temperature"] == 0.7
    assert provider.await_args.kwargs["max_tokens"] == 32


@pytest.mark.asyncio
async def test_streaming_is_rejected(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Reject streaming with HTTP 400 before invoking the provider."""
    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    })

    assert response.status_code == 400
    assert "Streaming" in response.json()["detail"]
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"messages": []}, {"temperature": -1}, {"temperature": 3},
    {"max_tokens": 0}, {"max_tokens": -1}, {"model": ""},
])
async def test_invalid_chat_requests(
    client: httpx.AsyncClient, provider: AsyncMock, override: dict[str, object]
) -> None:
    """Invalid supported parameters fail validation without a model call."""
    payload = {"model": "smartroute/auto",
               "messages": [{"role": "user", "content": "Hello"}]}
    response = await client.post("/v1/chat/completions", json=payload | override)

    assert response.status_code == 422
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unavailable", "http_error"])
async def test_provider_failures(
    client: httpx.AsyncClient, provider: AsyncMock, failure: str
) -> None:
    """Return useful gateway statuses without exposing upstream error details."""
    request = httpx.Request("POST", "http://provider.test/api/chat")
    if failure == "timeout":
        provider.side_effect = httpx.ReadTimeout("private upstream detail", request=request)
        expected_status = 504
    elif failure == "unavailable":
        provider.side_effect = httpx.ConnectError("private upstream detail", request=request)
        expected_status = 503
    else:
        provider.side_effect = httpx.HTTPStatusError(
            "private upstream detail", request=request,
            response=httpx.Response(404, request=request),
        )
        expected_status = 502

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto",
        "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == expected_status
    assert "private upstream detail" not in response.text


@pytest.mark.asyncio
async def test_openai_sdk_parses_completion(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """The official SDK preserves standard fields and SmartRoute extras."""
    async with AsyncOpenAI(
        base_url="http://test/v1", api_key="not-needed",
        http_client=client, max_retries=0,
    ) as sdk:
        response = await sdk.chat.completions.create(
            model="smartroute/auto",
            messages=[{"role": "user", "content": "Hello"}],
        )

    assert response.object == "chat.completion"
    assert response.choices[0].message.content == "Hello!"
    assert response.choices[0].finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.total_tokens == 15
    assert response.model_extra is not None
    assert response.model_extra["smartroute"]["tier_final"] == "small"
    assert response.model_extra["smartroute"]["request_id"] == response.id
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_sdk_rejects_streaming(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """The official SDK sees the expected 400 error for streaming requests."""
    async with AsyncOpenAI(
        base_url="http://test/v1", api_key="not-needed",
        http_client=client, max_retries=0,
    ) as sdk:
        with pytest.raises(BadRequestError) as caught:
            await sdk.chat.completions.create(
                model="smartroute/auto",
                messages=[{"role": "user", "content": "Hello"}],
                stream=True,
            )

    assert caught.value.status_code == 400
    provider.assert_not_awaited()