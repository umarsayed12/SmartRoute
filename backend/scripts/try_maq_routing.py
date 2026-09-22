"""Run a bounded, isolated routing smoke test against two explicitly approved MAQ models."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings, Tier
from app.providers import openai_compatible
from app.providers.base import ProviderResult
from app.routing import confidence, router
from app.schemas import ChatCompletionRequest, ChatMessage

MAQ_BASE_URL = "https://llm.maqsoftware.net/v1"
MODEL_IDS = {"small": "qwen-3.8-27b", "medium": "muse-glimmer-30b"}
MAX_OUTPUT_TOKENS = 512


class SmokeEnvironment(BaseSettings):
    """Read only the private MAQ credential from environment or the ignored backend file."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8", extra="ignore",
    )
    MAQ_API_KEY: SecretStr = SecretStr("")


class SmokeSettings(Settings):
    """Replace local model tiers only inside this standalone verification process."""

    MAQ_API_KEY: SecretStr = SecretStr("")

    @property
    def TIERS(self) -> list[Tier]:
        """Use Qwen as a test baseline and Muse as the next tier, without assumed prices."""
        return [
            Tier(name="small", provider="openai_compatible", model=MODEL_IDS["small"], base_url=MAQ_BASE_URL, api_key=self.MAQ_API_KEY),
            Tier(name="medium", provider="openai_compatible", model=MODEL_IDS["medium"], base_url=MAQ_BASE_URL, api_key=self.MAQ_API_KEY),
        ]


async def run_smoke(api_key: SecretStr) -> dict[str, Any]:
    """Run four synthetic cases, with at most seven bounded provider calls and no database writes."""
    if not api_key.get_secret_value().strip():
        raise ValueError("Configure MAQ_API_KEY locally before running this test.")
    configured = SmokeSettings(
        _env_file=None, MAQ_API_KEY=api_key, APP_MODE="local", LARGE_MODEL="",
        ROUTING_MODE_PREFERENCE="heuristic_only", CONFIDENCE_THRESHOLD=0.6, MAX_ESCALATIONS=1,
        REFERENCE_INPUT_PRICE_PER_1K=0, REFERENCE_OUTPUT_PRICE_PER_1K=0,
    )
    original_chat = openai_compatible.chat
    attempts: list[dict[str, Any]] = []

    async def call(
        model: str, messages: list[dict[str, str]], temperature: float = 0.2,
        max_tokens: int | None = None, *, base_url: str | None = None,
        api_key: str | None = None, kind: str = "answer",
    ) -> ProviderResult:
        """Enforce the fixed endpoint/model allowlist and record only non-secret usage metadata."""
        if model not in MODEL_IDS.values() or base_url not in (None, MAQ_BASE_URL):
            raise ValueError("This smoke test only permits its two fixed MAQ models and endpoint.")
        if max_tokens is None or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS or len(attempts) >= 7:
            raise ValueError("Smoke-test request budget exceeded.")
        attempts.append({"kind": kind, "model": model, "max_tokens": max_tokens, "completed": False})
        result = await original_chat(
            model, messages, temperature, max_tokens,
            base_url=MAQ_BASE_URL, api_key=configured.MAQ_API_KEY.get_secret_value(),
        )
        attempts[-1].update({
            "completed": True, "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens, "latency_ms": result.latency_ms,
        })
        if not isinstance(result.content, str) or not result.content.strip():
            print(json.dumps({"diagnostic": "empty_answer_text", "attempt": attempts[-1]}), flush=True)
            raise ValueError("The provider returned no text within the smoke-test output limit.")
        return result

    async def self_check_chat(
        model: str, messages: list[dict[str, str]], temperature: float = 0.0,
        max_tokens: int | None = None, *, base_url: str | None = None,
    ) -> ProviderResult:
        """Send the existing confidence check to the same approved remote model, not Ollama."""
        return await call(model, messages, temperature, max_tokens, base_url=MAQ_BASE_URL, kind="self_check")

    cases = [
        ("forced-baseline", "smartroute/small", "Say hello in one short sentence."),
        ("forced-next-tier", "smartroute/medium", "Say hello in one short sentence."),
        ("auto-simple", "smartroute/auto", "What is the capital of France?"),
        ("auto-reasoning", "smartroute/auto", "Explain why caching can reduce latency in two sentences."),
    ]
    results = []
    with patch.object(router, "settings", configured), patch.object(confidence, "settings", configured), patch.object(openai_compatible, "chat", call), patch.object(confidence.ollama, "chat", self_check_chat):
        for case, mode, prompt in cases:
            before = len(attempts)
            result, routing = await router.route_and_answer(ChatCompletionRequest(
                model=mode, messages=[ChatMessage(role="user", content=prompt)],
                temperature=0.2, max_tokens=MAX_OUTPUT_TOKENS,
            ))
            results.append({
                "case": case, "tier_chosen": routing.tier_chosen, "tier_final": routing.tier_final,
                "model": result.model, "answer": result.content, "escalated": routing.escalated,
                "confidence": routing.confidence, "reason": routing.reason,
                "routing_latency_ms": routing.latency_ms, "attempts": attempts[before:],
            })
    return {
        "scope": "Isolated local routing smoke test; not hosted workspace inference or a quality benchmark.",
        "mapping": MODEL_IDS,
        "max_answer_tokens": MAX_OUTPUT_TOKENS,
        "cost_usd": None,
        "cost_note": "Provider prices were not supplied; no cost or savings estimate is reported.",
        "confidence_note": "Routing signal only; the highest test tier returns 1.0 by convention.",
        "usage_note": "Token counts are provider-reported; zero can mean that usage was omitted.",
        "provider_calls": len(attempts), "results": results,
    }


def main() -> None:
    """Print a non-secret measured report, or a redacted failure without response bodies."""
    try:
        report = asyncio.run(run_smoke(SmokeEnvironment().MAQ_API_KEY))
    except httpx.HTTPStatusError as error:
        raise SystemExit(f"MAQ smoke test failed with HTTP {error.response.status_code}; check access, model availability, and the local key.") from None
    except ValueError as error:
        safe_messages = {
            "Configure MAQ_API_KEY locally before running this test.",
            "The provider returned no text within the smoke-test output limit.",
            "This smoke test only permits its two fixed MAQ models and endpoint.",
            "Smoke-test request budget exceeded.",
        }
        message = str(error) if str(error) in safe_messages else "Invalid provider response or test configuration."
        raise SystemExit(f"MAQ smoke test stopped: {message}") from None
    except Exception as error:
        raise SystemExit(f"MAQ smoke test failed ({type(error).__name__}); no credentials or provider error body were displayed.") from None
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()