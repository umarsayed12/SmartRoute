"""Verify configuration defaults, provider contracts, and backend health."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.config import Settings
from app.providers import ollama, openai_compatible

MockHttp = Callable[[Callable[[httpx.Request], httpx.Response]], None]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings tests independent of the developer's environment."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)
    for module in (main, ollama, openai_compatible):
        monkeypatch.setattr(module, "settings", configured)


def test_default_tiers_and_fallback() -> None:
    """Default local tiers are free and disabled large resolves to medium."""
    configured = Settings(_env_file=None)

    assert [tier.name for tier in configured.TIERS] == ["small", "medium", "large"]
    assert [tier.model for tier in configured.TIERS[:2]] == ["qwen2.5:1.5b", "qwen2.5:7b"]
    assert all(tier.input_price_per_1k == tier.output_price_per_1k == 0 for tier in configured.TIERS)
    assert not configured.TIERS[2].enabled
    assert configured.get_tier("large") == configured.get_tier("medium")
    assert configured.CONFIDENCE_THRESHOLD == 0.6
    assert configured.MAX_ESCALATIONS == 1
    assert configured.REFERENCE_INPUT_PRICE_PER_1K == 0.0025
    assert configured.REFERENCE_OUTPUT_PRICE_PER_1K == 0.010


def test_large_tier_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured remote model enables large and loads its prices."""
    monkeypatch.setenv("LARGE_MODEL", "example-model")
    monkeypatch.setenv("LARGE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LARGE_INPUT_PRICE", "0.001")
    monkeypatch.setenv("LARGE_OUTPUT_PRICE", "0.002")

    tier = Settings(_env_file=None).get_tier("large")

    assert tier.name == "large"
    assert tier.enabled
    assert tier.provider == "openai_compatible"
    assert tier.model == "example-model"
    assert tier.base_url == "https://example.test/v1"
    assert tier.input_price_per_1k == 0.001
    assert tier.output_price_per_1k == 0.002


def test_unknown_tier_is_rejected() -> None:
    """Misspelled tier names must not silently select a model."""
    with pytest.raises(ValueError, match="Unknown tier"):
        Settings(_env_file=None).get_tier("unknown")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CONFIDENCE_THRESHOLD", "-0.1"),
        ("CONFIDENCE_THRESHOLD", "1.1"),
        ("MAX_ESCALATIONS", "-1"),
        ("LARGE_INPUT_PRICE", "-0.001"),
    ],
)
def test_invalid_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    """Reject settings that would make confidence or cost calculations invalid."""
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_tokens", [None, 32])
async def test_ollama_chat(mock_http: MockHttp, max_tokens: int | None) -> None:
    """Map chat options, generated text, and Ollama's actual token counts."""
    messages = [{"role": "user", "content": "Hello"}]

    def handle(request: httpx.Request) -> httpx.Response:
        """Check the outbound request and return a representative Ollama reply."""
        assert request.method == "POST"
        assert str(request.url) == "http://localhost:11434/api/chat"
        options = {"temperature": 0.4}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        assert json.loads(request.content) == {
            "model": "qwen2.5:1.5b",
            "messages": messages,
            "stream": False,
            "options": options,
        }
        return httpx.Response(200, json={
            "model": "qwen2.5:1.5b",
            "message": {"role": "assistant", "content": "Hello!"},
            "prompt_eval_count": 12,
            "eval_count": 3,
        })

    mock_http(handle)
    result = await ollama.chat(
        "qwen2.5:1.5b", messages, temperature=0.4, max_tokens=max_tokens
    )

    assert result.content == "Hello!"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert result.model == "qwen2.5:1.5b"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/v1", "/v1/"])
@pytest.mark.parametrize("max_tokens", [None, 32])
async def test_openai_chat(
    mock_http: MockHttp, suffix: str, max_tokens: int | None
) -> None:
    """Accept either API root form, send bearer auth, and preserve usage."""
    messages = [{"role": "user", "content": "Hello"}]

    def handle(request: httpx.Request) -> httpx.Response:
        """Validate the OpenAI request and supply a minimal completion."""
        assert request.method == "POST"
        assert str(request.url) == "https://example.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-only-key"
        payload = json.loads(request.content)
        assert payload["model"] == "example-model"
        assert payload["messages"] == messages
        assert payload["temperature"] == 0.2
        assert payload["stream"] is False
        if max_tokens is None:
            assert "max_tokens" not in payload
        else:
            assert payload["max_tokens"] == max_tokens
        return httpx.Response(200, json={
            "model": "example-model-version",
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2},
        })

    mock_http(handle)
    result = await openai_compatible.chat(
        "example-model", messages, max_tokens=max_tokens,
        base_url=f"https://example.test{suffix}", api_key="test-only-key",
    )

    assert result.content == "Hello!"
    assert result.prompt_tokens == 8
    assert result.completion_tokens == 2
    assert result.model == "example-model-version"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [ollama, openai_compatible])
async def test_provider_http_errors(mock_http: MockHttp, provider: Any) -> None:
    """Do not convert failed provider requests into successful empty answers."""
    mock_http(lambda request: httpx.Response(503, json={"error": "unavailable"}))

    with pytest.raises(httpx.HTTPStatusError):
        await provider.chat(
            "example-model", [{"role": "user", "content": "Hello"}],
            base_url="https://example.test",
        )


@pytest.mark.asyncio
async def test_openai_requires_a_base_url() -> None:
    """An unconfigured remote provider fails before making an HTTP request."""
    with pytest.raises(ValueError, match="LARGE_BASE_URL"):
        await openai_compatible.chat("example-model", [])


@pytest.mark.parametrize("state", ["ok", "http_error", "timeout", "unreachable"])
@pytest.mark.parametrize("large_enabled", [False, True])
def test_health(
    mock_http: MockHttp, monkeypatch: pytest.MonkeyPatch,
    state: str, large_enabled: bool,
) -> None:
    """Health stays available when Ollama fails and lists only enabled tiers."""
    if large_enabled:
        monkeypatch.setattr(main, "settings", Settings(
            _env_file=None, LARGE_MODEL="example-model",
            LARGE_BASE_URL="https://example.test",
        ))

    def handle(request: httpx.Request) -> httpx.Response:
        """Simulate healthy, unavailable, or timed-out Ollama tag requests."""
        assert request.method == "GET"
        assert str(request.url) == "http://localhost:11434/api/tags"
        assert all(value == 1.0 for value in request.extensions["timeout"].values())
        if state == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if state == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(503 if state == "http_error" else 200, json={"models": []})

    mock_http(handle)
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "tiers": ["small", "medium", "large"] if large_enabled else ["small", "medium"],
        "ollama": state == "ok",
    }


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://untrusted.test"])
def test_cors_origin(origin: str) -> None:
    """Only the configured Vite development origin passes CORS preflight."""
    with TestClient(main.app) as client:
        response = client.options("/health", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        })

    if origin == "http://localhost:5173":
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    else:
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers