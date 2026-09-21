"""Verify chat compatibility, routing, costs, and complete background request logs."""

import json
from datetime import datetime
from time import time
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import AsyncOpenAI, BadRequestError

from app import db
from app.config import Settings
from app.providers.base import ProviderResult
from app.routing import confidence
from app.routing import router as routing_router
from app.routing.features import extract_features


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub provider calls and confidence so API tests never make network requests."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)
    monkeypatch.setattr(routing_router, "settings", configured)
    monkeypatch.setattr(confidence, "settings", configured)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=0.9))
    mocked = AsyncMock(return_value=ProviderResult(
        content="Hello!", prompt_tokens=12, completion_tokens=3,
        latency_ms=17, model="qwen2.5:1.5b",
    ))
    monkeypatch.setattr(routing_router.ollama, "chat", mocked)
    return mocked


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["smartroute/auto", "other-model", "smartroute/unknown", "small"])
async def test_chat_response(
    client: httpx.AsyncClient, provider: AsyncMock, model: str
) -> None:
    """Auto and unrecognized model names use the heuristic and return a completion."""
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
    assert routing["confidence"] == 0.9
    assert routing["routing_mode"] == "heuristic"
    assert routing["reason"]
    assert routing["latency_ms"] >= 0
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
    assert db.list_requests()["total"] == 0


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
    assert db.list_requests()["total"] == 0


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
    assert db.list_requests()["total"] == 0


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


@pytest.mark.asyncio
@pytest.mark.parametrize(("prompt", "chosen_tier", "reason_cue"), [
    ("Explain recursion", "medium", "reasoning"),
    ("Give me a detailed essay on databases", "large", "disabled"),
])
async def test_heuristic_medium_and_disabled_large(
    client: httpx.AsyncClient, provider: AsyncMock,
    prompt: str, chosen_tier: str, reason_cue: str,
) -> None:
    """Select medium directly or resolve disabled large without an escalation."""
    provider.return_value.model = "qwen2.5:7b"
    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto",
        "messages": [{"role": "user", "content": prompt}],
    })

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "qwen2.5:7b"
    routing = data["smartroute"]
    assert routing["tier_chosen"] == chosen_tier
    assert routing["tier_final"] == "medium"
    assert routing["routing_mode"] == "heuristic"
    assert routing["escalated"] is False
    assert routing["confidence"] == 0.9
    assert routing["actual_cost_usd"] == 0
    assert reason_cue in routing["reason"]
    provider.assert_awaited_once_with(
        model="qwen2.5:7b", messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=None, base_url="http://localhost:11434",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["smartroute/auto", "smartroute/large"])
async def test_enabled_large_provider_and_costs(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    """Use remote configuration and actual usage prices when large is enabled."""
    monkeypatch.setattr(routing_router, "settings", Settings(
        _env_file=None,
        LARGE_MODEL="example-large", LARGE_BASE_URL="https://example.test/v1",
        LARGE_API_KEY="test-only-key", LARGE_INPUT_PRICE=0.1, LARGE_OUTPUT_PRICE=0.2,
        REFERENCE_INPUT_PRICE_PER_1K=0.5, REFERENCE_OUTPUT_PRICE_PER_1K=1.0,
    ))
    remote_provider = AsyncMock(return_value=ProviderResult(
        content="A detailed answer.", prompt_tokens=20, completion_tokens=10,
        latency_ms=45, model="example-large-version",
    ))
    monkeypatch.setattr(routing_router.openai_compatible, "chat", remote_provider)
    messages = [{"role": "user", "content": "Write a detailed essay"}]

    response = await client.post("/v1/chat/completions", json={
        "model": model, "messages": messages,
        "temperature": 0.7, "max_tokens": 64,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "example-large-version"
    assert data["usage"]["total_tokens"] == 30
    routing = data["smartroute"]
    assert routing["tier_chosen"] == routing["tier_final"] == "large"
    assert routing["routing_mode"] == ("forced" if model == "smartroute/large" else "heuristic")
    assert routing["escalated"] is False
    assert routing["confidence"] == 0.9
    assert routing["latency_ms"] >= 0
    assert routing["actual_cost_usd"] == pytest.approx(0.004)
    assert routing["reference_cost_usd"] == pytest.approx(0.020)
    assert "test-only-key" not in response.text
    remote_provider.assert_awaited_once_with(
        model="example-large", messages=messages, temperature=0.7, max_tokens=64,
        base_url="https://example.test/v1", api_key="test-only-key",
    )
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("model", "chosen", "final", "provider_model"), [
    ("smartroute/small", "small", "small", "qwen2.5:1.5b"),
    ("smartroute/medium", "medium", "medium", "qwen2.5:7b"),
    ("smartroute/large", "large", "medium", "qwen2.5:7b"),
])
async def test_forced_tiers_do_not_escalate(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    model: str, chosen: str, final: str, provider_model: str,
) -> None:
    """Forced modes bypass heuristic selection and stay fixed even at low confidence."""
    picker = Mock(side_effect=AssertionError("Forced routing must skip the heuristic."))
    monkeypatch.setattr(routing_router, "pick_tier", picker)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=0.1))
    provider.return_value.model = provider_model

    response = await client.post("/v1/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": "Write a comprehensive essay"}],
    })

    assert response.status_code == 200
    routing = response.json()["smartroute"]
    assert routing["tier_chosen"] == chosen
    assert routing["tier_final"] == final
    assert routing["routing_mode"] == "forced"
    assert routing["confidence"] == 0.1
    assert routing["escalated"] is False
    assert provider.await_args.kwargs["model"] == provider_model
    provider.assert_awaited_once()
    picker.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("first_score", "limit", "calls"), [
    (0.9, 1, 1), (0.6, 1, 1), (0.59, 0, 1), (0.59, 1, 2), (0.0, 5, 2),
])
async def test_escalation_threshold_and_enabled_tiers(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    first_score: float, limit: int, calls: int,
) -> None:
    """Use a strict threshold, honor zero budget, and never repeat disabled large's fallback."""
    routing_router.settings.MAX_ESCALATIONS = limit
    provider.side_effect = [
        ProviderResult("First answer", 12, 3, 17, "qwen2.5:1.5b"),
        ProviderResult("Second answer", 20, 5, 25, "qwen2.5:7b"),
    ]
    scorer = AsyncMock(side_effect=[first_score, 0.2])
    monkeypatch.setattr(routing_router, "score", scorer)

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.7, "max_tokens": 32,
    })

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]
    assert routing["tier_chosen"] == "small"
    assert routing["tier_final"] == ("medium" if calls == 2 else "small")
    assert routing["escalated"] is (calls == 2)
    assert routing["confidence"] == (0.2 if calls == 2 else first_score)
    assert data["usage"]["total_tokens"] == (25 if calls == 2 else 15)
    assert [call.kwargs["model"] for call in provider.await_args_list] == [
        "qwen2.5:1.5b", "qwen2.5:7b",
    ][:calls]
    assert all(call.kwargs["max_tokens"] == 32 for call in provider.await_args_list)
    assert all(call.kwargs["temperature"] == 0.7 for call in provider.await_args_list)
    assert scorer.await_count == calls
    if calls == 2:
        assert "escalating small to medium" in routing["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "total_cost", "reference_cost", "final_tier"), [
    (1, 0.102, 0.00011, "medium"),
    (2, 0.300, 0.000155, "large"),
])
async def test_escalation_budget_and_total_costs(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    limit: int, total_cost: float, reference_cost: float, final_tier: str,
) -> None:
    """Sum all answer costs, use final-token reference cost, and time the whole cascade."""
    configured = Settings(
        _env_file=None, MAX_ESCALATIONS=limit,
        LARGE_MODEL="example-large", LARGE_BASE_URL="https://example.test/v1",
        LARGE_INPUT_PRICE=5.0, LARGE_OUTPUT_PRICE=6.0,
    )
    tiers = configured.TIERS
    tiers[0].input_price_per_1k, tiers[0].output_price_per_1k = 1.0, 2.0
    tiers[1].input_price_per_1k, tiers[1].output_price_per_1k = 3.0, 4.0
    monkeypatch.setattr(Settings, "TIERS", property(lambda _settings: tiers))
    monkeypatch.setattr(routing_router, "settings", configured)
    monkeypatch.setattr(routing_router, "score", AsyncMock(side_effect=[0.1, 0.2, 1.0]))
    monkeypatch.setattr(routing_router, "perf_counter", Mock(side_effect=[100.0, 100.5]))
    provider.side_effect = [
        ProviderResult("Small answer", 10, 4, 10, "qwen2.5:1.5b"),
        ProviderResult("Medium answer", 20, 6, 20, "qwen2.5:7b"),
    ]
    remote_provider = AsyncMock(return_value=ProviderResult(
        "Large answer", 30, 8, 30, "example-large",
    ))
    monkeypatch.setattr(routing_router.openai_compatible, "chat", remote_provider)

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]
    assert routing["tier_chosen"] == "small"
    assert routing["tier_final"] == final_tier
    assert routing["escalated"] is True
    assert routing["actual_cost_usd"] == pytest.approx(total_cost)
    assert routing["reference_cost_usd"] == pytest.approx(reference_cost)
    assert routing["latency_ms"] == 500
    assert data["usage"]["total_tokens"] == (26 if limit == 1 else 38)
    assert provider.await_count == 2
    assert remote_provider.await_count == limit - 1
    if limit == 1:
        assert "Escalation limit reached" in routing["reason"]


@pytest.mark.asyncio
async def test_real_confidence_drives_cascade(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real scorer, its four-token check, and the final top-tier answer."""
    monkeypatch.setattr(routing_router, "score", confidence.score)
    provider.side_effect = [
        ProviderResult("I don't know.", 12, 4, 10, "qwen2.5:1.5b"),
        ProviderResult("0", 25, 1, 5, "qwen2.5:1.5b"),
        ProviderResult("Paris is the capital of France.", 20, 8, 20, "qwen2.5:7b"),
    ]
    question = "What is the capital of France?"
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": question},
    ]

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": messages, "max_tokens": 32,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["choices"][0]["message"]["content"] == "Paris is the capital of France."
    assert data["smartroute"]["tier_chosen"] == "small"
    assert data["smartroute"]["tier_final"] == "medium"
    assert data["smartroute"]["escalated"] is True
    assert data["smartroute"]["confidence"] == 1.0
    assert data["usage"]["total_tokens"] == 28
    assert [call.kwargs["max_tokens"] for call in provider.await_args_list] == [32, 4, 32]
    assert [call.kwargs["model"] for call in provider.await_args_list] == [
        "qwen2.5:1.5b", "qwen2.5:1.5b", "qwen2.5:7b",
    ]
    checking_prompt = provider.await_args_list[1].kwargs["messages"][1]["content"]
    assert question in checking_prompt
    assert "Hello" not in checking_prompt
    assert provider.await_args_list[2].kwargs["messages"] == messages
    assert db.list_requests()["total"] == 1
    stored = db.get_request(data["id"])
    assert stored is not None
    assert stored["answer_full"] == "Paris is the capital of France."
    assert stored["escalated"] is True
    assert stored["prompt_tokens"] == 20
    assert stored["completion_tokens"] == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "api", "playground", "testlab", "sdk"])
async def test_background_request_log(
    client: httpx.AsyncClient, provider: AsyncMock, source: str | None
) -> None:
    """Persist the complete conversation, feature vector, and returned routing metadata."""
    latest_prompt = "Latest caf\u00e9 question.\n" * 20
    messages = [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": latest_prompt},
    ]
    headers = {"X-SmartRoute-Source": source} if source is not None else {}
    response = await client.post("/v1/chat/completions", headers=headers, json={
        "model": "smartroute/small", "messages": messages,
    })

    assert response.status_code == 200
    data = response.json()
    detail = await client.get(f"/v1/requests/{data['id']}")
    assert detail.status_code == 200
    stored = detail.json()
    assert stored["id"] == data["id"]
    assert stored["source"] == (source or "api")
    assert stored["prompt_preview"] == " ".join(latest_prompt.split())[:200]
    assert json.loads(stored["prompt_full"]) == messages
    assert json.loads(stored["features_json"]) == extract_features(messages)
    assert stored["answer_full"] == data["choices"][0]["message"]["content"]
    assert stored["prompt_tokens"] == data["usage"]["prompt_tokens"]
    assert stored["completion_tokens"] == data["usage"]["completion_tokens"]
    created_at = datetime.fromisoformat(stored["created_at"])
    assert created_at.utcoffset().total_seconds() == 0
    assert int(created_at.timestamp()) == data["created"]
    assert stored["feedback"] is None
    assert stored["feedback_note"] is None
    for field, value in data["smartroute"].items():
        assert stored["id" if field == "request_id" else field] == value
    assert db.list_requests()["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["unknown", ""])
async def test_invalid_request_source(
    client: httpx.AsyncClient, provider: AsyncMock, source: str
) -> None:
    """Reject unknown source labels before model execution or request logging."""
    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    }, headers={"X-SmartRoute-Source": source})

    assert response.status_code == 422
    provider.assert_not_awaited()
    assert db.list_requests()["total"] == 0