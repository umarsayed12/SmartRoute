"""Test answer-confidence penalties, self-check parsing, and top-tier behavior."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderResult
from app.routing import confidence


@pytest.fixture(autouse=True)
def configured(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolate confidence checks from local environment files and overrides."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(confidence, "settings", settings)
    return settings


@pytest.mark.parametrize(("question", "answer", "expected"), [
    ("What is Python?", "Python is a programming language used for many tasks.", 1.0),
    ("Hello?", "", 0.0),
    ("Hello?", " \t\n", 0.0),
    ("Hello?", "...", 0.0),
    ("Name a number", "42", 0.75),
    ("Name a city", "I'm not sure which city you mean.", 0.5),
    ("Name a city", "I am not sure which city you mean.", 0.5),
    ("Name a city", "I don't know.", 0.25),
    ("Name a city", "I don\u2019t know.", 0.25),
    ("Name a city", "I do not know which city you mean.", 0.5),
    ("Name a city", "As an AI, I cannot determine that answer.", 0.5),
    ("Why is the sky blue?", "WHY IS THE SKY BLUE!", 0.25),
    ("Why?", "why?", 0.0),
    ("I'm not sure?", "I'm not sure.", 0.0),
    ("Describe aircraft", "An aircraft can serve as an airliner on scheduled flights.", 1.0),
])
def test_heuristic_confidence(question: str, answer: str, expected: float) -> None:
    """Apply bounded penalties without matching hedges inside unrelated words."""
    assert confidence.heuristic_confidence(question, answer) == pytest.approx(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "expected"), [
    ("0", 0.0), ("10", 1.0), (" 8\n", 0.8),
    ("", 0.5), ("8/10", 0.5), ("8.5", 0.5), ("confident", 0.5),
    ("-1", 0.5), ("11", 0.5),
])
async def test_self_check_parsing(
    monkeypatch: pytest.MonkeyPatch, reply: str, expected: float
) -> None:
    """Parse only integer ratings in range and constrain the checker generation."""
    provider = AsyncMock(return_value=ProviderResult(
        content=reply, prompt_tokens=20, completion_tokens=1,
        latency_ms=5, model="qwen2.5:1.5b",
    ))
    monkeypatch.setattr(confidence.ollama, "chat", provider)

    result = await confidence.self_check("qwen2.5:1.5b", "What is Python?", "A language.")

    assert result == expected
    provider.assert_awaited_once()
    options = provider.await_args.kwargs
    assert options["model"] == "qwen2.5:1.5b"
    assert options["temperature"] == 0.0
    assert options["max_tokens"] == 4
    assert options["base_url"] == "http://localhost:11434"
    assert "Reply with only the number" in options["messages"][0]["content"]
    assert "What is Python?" in options["messages"][1]["content"]
    assert "A language." in options["messages"][1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "connection", "http_status"])
async def test_unavailable_self_check(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """A failed auxiliary check does not discard an already generated answer."""
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    if failure == "timeout":
        error = httpx.ReadTimeout("unavailable", request=request)
    elif failure == "connection":
        error = httpx.ConnectError("unavailable", request=request)
    else:
        error = httpx.HTTPStatusError(
            "unavailable", request=request, response=httpx.Response(503, request=request)
        )
    monkeypatch.setattr(confidence.ollama, "chat", AsyncMock(side_effect=error))

    assert await confidence.self_check("qwen2.5:1.5b", "Question", "Answer") == 0.5


@pytest.mark.asyncio
async def test_combined_score(configured: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Combine the text heuristic and self-check with equal weights."""
    checker = AsyncMock(return_value=0.4)
    monkeypatch.setattr(confidence, "self_check", checker)
    question = "What is Python?"
    answer = "Python is a programming language used for many tasks."

    result = await confidence.score(question, answer, configured.get_tier("small"))

    assert result == pytest.approx(0.7)
    checker.assert_awaited_once_with("qwen2.5:1.5b", question, answer)


@pytest.mark.asyncio
@pytest.mark.parametrize("large_enabled", [False, True])
async def test_top_enabled_tier_skips_self_check(
    configured: Settings, monkeypatch: pytest.MonkeyPatch, large_enabled: bool
) -> None:
    """Medium is the top tier unless a remote large model has been enabled."""
    if large_enabled:
        configured.LARGE_MODEL = "example-large"
        configured.LARGE_BASE_URL = "https://example.test/v1"
    checker = AsyncMock()
    monkeypatch.setattr(confidence, "self_check", checker)

    result = await confidence.score("Question", "", configured.get_tier("large"))

    assert result == 1.0
    checker.assert_not_awaited()


@pytest.mark.asyncio
async def test_medium_checks_when_large_enabled(
    configured: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Medium still performs a local self-check when another tier is available."""
    configured.LARGE_MODEL = "example-large"
    configured.LARGE_BASE_URL = "https://example.test/v1"
    checker = AsyncMock(return_value=0.8)
    monkeypatch.setattr(confidence, "self_check", checker)
    answer = "A complete answer containing enough context."

    assert await confidence.score("Question", answer, configured.get_tier("medium")) == 0.9
    checker.assert_awaited_once_with("qwen2.5:7b", "Question", answer)