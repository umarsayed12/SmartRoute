"""Verify fixed-endpoint MAQ routing tests without sending credentials or prompts to a live service."""

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest
from pydantic import SecretStr

from app.providers import openai_compatible
from app.routing import confidence, router
from scripts import try_maq_routing as smoke


@pytest.mark.asyncio
@pytest.mark.parametrize("check_reply", ["10", "0", "unparseable"])
async def test_bounded_maq_routing(
    mock_http: Callable, isolated_database: Path, check_reply: str
) -> None:
    """Exercise real router logic with two remote adapters, including self-checks and escalation."""
    calls = []
    original_settings, original_chat, original_check = router.settings, openai_compatible.chat, confidence.ollama.chat

    def handle(request: httpx.Request) -> httpx.Response:
        """Reject any URL/model outside the test's allowlist and return controlled token usage."""
        assert str(request.url) == "https://llm.maqsoftware.net/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] in smoke.MODEL_IDS.values()
        assert payload["max_tokens"] in (4, 512)
        answer = check_reply if payload["max_tokens"] == 4 else "A complete test answer with enough detail."
        return httpx.Response(200, json={
            "model": payload["model"], "choices": [{"message": {"content": answer}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 4},
        })

    mock_http(handle)
    report = await smoke.run_smoke(SecretStr("synthetic-test-key"))

    assert len(report["results"]) == 4
    assert report["provider_calls"] == len(calls) <= 7
    assert report["results"][0]["model"] == "qwen-3.8-27b"
    assert report["results"][1]["model"] == "muse-glimmer-30b"
    assert report["results"][2]["tier_chosen"] == "small"
    assert report["results"][2]["escalated"] is (check_reply == "0")
    assert report["results"][3]["tier_chosen"] == "medium"
    assert report["cost_usd"] is None
    assert "synthetic-test-key" not in json.dumps(report)
    assert router.settings is original_settings
    assert openai_compatible.chat is original_chat
    assert confidence.ollama.chat is original_check
    assert not isolated_database.exists()


@pytest.mark.asyncio
async def test_missing_key_and_failed_provider_restore_state(mock_http: Callable) -> None:
    """Do not fall back to local inference or retain overrides after a failed remote call."""
    with pytest.raises(ValueError):
        await smoke.run_smoke(SecretStr(""))
    original_settings, original_chat = router.settings, openai_compatible.chat
    mock_http(lambda request: httpx.Response(401, json={"error": "private upstream detail"}))

    with pytest.raises(httpx.HTTPStatusError):
        await smoke.run_smoke(SecretStr("synthetic-test-key"))

    assert router.settings is original_settings
    assert openai_compatible.chat is original_chat


@pytest.mark.asyncio
async def test_empty_answer_reports_only_safe_usage(
    mock_http: Callable, capsys: pytest.CaptureFixture[str]
) -> None:
    """A token-exhausted/non-text response reports usage without exposing credentials or raw payloads."""
    mock_http(lambda request: httpx.Response(200, json={
        "model": "qwen-3.8-27b", "choices": [{"message": {"content": "", "reasoning_content": "private reasoning"}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 64},
    }))
    with pytest.raises(ValueError, match="no text"):
        await smoke.run_smoke(SecretStr("synthetic-test-key"))
    output = capsys.readouterr().out
    assert "empty_answer_text" in output
    assert "synthetic-test-key" not in output
    assert "private reasoning" not in output