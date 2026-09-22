"""Route exclusively through owned cloud models and audit every answer and confidence attempt."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import httpx
import joblib
from pydantic import ConfigDict, Field, model_validator
from sklearn.pipeline import Pipeline
from starlette.concurrency import run_in_threadpool

from app.hosted import providers
from app.hosted.config import HostedSettings
from app.hosted.store import Principal, WorkspaceStore
from app.routing.confidence import heuristic_confidence
from app.routing.features import FEATURE_ORDER, extract_features
from app.routing.heuristic import pick_tier
from app.schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage, Choice, RoutingInfo, Usage

TIER_ORDER = ["small", "medium", "large"]


class HostedMessage(ChatMessage):
    """Bound text-only conversation roles and message sizes for the cloud gateway."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=64000)


class HostedChatRequest(ChatCompletionRequest):
    """Reject unsupported tools/media and bound generation and conversation sizes."""

    model_config = ConfigDict(extra="forbid")
    messages: list[HostedMessage] = Field(min_length=1, max_length=128)
    max_tokens: int = Field(default=1024, ge=1, le=4096)

    @model_validator(mode="after")
    def check_conversation(self) -> "HostedChatRequest":
        """Require a user message and enforce an aggregate input bound before inference."""
        if not any(message.role == "user" for message in self.messages) or sum(len(message.content) for message in self.messages) > 64000:
            raise ValueError("A bounded conversation containing a user message is required.")
        return self


class RoutingFailure(RuntimeError):
    """Carry a redacted gateway failure and the optional persisted request ID."""

    def __init__(self, detail: str, status: int = 409, request_id: str | None = None) -> None:
        """Preserve safe public failure metadata without upstream response bodies."""
        super().__init__(detail)
        self.status = status
        self.request_id = request_id


def _learned(artifact: dict[str, Any] | None, features: dict[str, float]) -> tuple[str, str] | None:
    """Use only a trusted, scoped classifier with the current feature contract."""
    if not artifact or artifact["feature_order"] != FEATURE_ORDER:
        return None
    try:
        model = joblib.load(BytesIO(artifact["artifact"]))
        if not isinstance(model, Pipeline) or model.n_features_in_ != len(FEATURE_ORDER) or not set(model.classes_).issubset(TIER_ORDER):
            return None
        probabilities = model.predict_proba([[features[name] for name in FEATURE_ORDER]])[0]
        index = int(probabilities.argmax())
        return str(model.classes_[index]), f"Workspace learned policy (probability {float(probabilities[index]):.2f})."
    except Exception:
        return None


async def route_and_log(
    actor: Principal, store: WorkspaceStore, configured: HostedSettings, client: httpx.AsyncClient,
    request: HostedChatRequest, source: str,
) -> ChatCompletionResponse:
    """Generate one metered response without global models, credentials, settings, or log storage."""
    if request.stream:
        raise RoutingFailure("Streaming is not supported yet.", 400)
    models = await run_in_threadpool(store.model_rows, actor)
    models = sorted([model for model in models if model["enabled"]], key=lambda model: TIER_ORDER.index(model["tier"]))
    if not models:
        raise RoutingFailure("Configure at least one enabled workspace model before sending requests.")
    settings = await run_in_threadpool(store.settings, actor)
    messages = [message.model_dump() for message in request.messages]
    features = extract_features(messages)
    requested = request.model.removeprefix("smartroute/")
    forced = request.model.startswith("smartroute/") and requested in TIER_ORDER
    mode = "forced" if forced else "heuristic"
    if forced:
        if not any(model["tier"] == requested for model in models):
            raise RoutingFailure("The forced tier is not configured and enabled in this workspace.")
        chosen, reason = requested, f"Forced workspace {requested} tier."
    else:
        prediction = None
        if settings.routing_mode_preference != "heuristic_only":
            prediction = await run_in_threadpool(_learned, await run_in_threadpool(store.classifier, actor), features)
        if prediction:
            chosen, reason = prediction
            mode = "learned"
        elif settings.routing_mode_preference == "learned_only":
            raise RoutingFailure("Learned-only routing requires a usable workspace model.", 503)
        else:
            chosen, reason = pick_tier(features)
    model = next((item for item in models if TIER_ORDER.index(item["tier"]) >= TIER_ORDER.index(chosen)), models[-1])
    if model["tier"] != chosen:
        reason += f" {chosen.capitalize()} is not enabled; using owned {model['tier']} tier."
    question = next(message["content"] for message in reversed(messages) if message["role"] == "user")
    request_id = f"chatcmpl-{uuid4().hex}"
    created = datetime.now(timezone.utc)
    started = perf_counter()
    attempts: list[dict[str, Any]] = []
    escalations = 0
    result: providers.Completion | None = None
    score = 0.0

    async def call(kind: str, content: list[dict[str, str]], tokens: int) -> providers.Completion:
        """Decrypt the owned key for one call and record reported usage or an unknown-cost failure."""
        call_started = perf_counter()
        attempt = {
            "kind": kind, "tier": model["tier"], "provider": model["provider"], "model": model["model"],
            "status": "failed", "error_code": None, "prompt_tokens": 0, "completion_tokens": 0,
            "latency_ms": 0, "cost_usd": None, "usage_details": {"usage_known": False},
        }
        try:
            provider, secret = await run_in_threadpool(store.provider_key, actor, model["credential_id"], configured)
            if provider != model["provider"]:
                raise providers.ProviderFailure("credential_provider_mismatch")
            temperature = (request.temperature if kind == "answer" else 0.0) if model["send_temperature"] else None
            completion = await providers.chat(client, provider, model["model"], secret, content, temperature, tokens)
            cost = (Decimal(completion.prompt_tokens) * model["input_price_per_1k"] + Decimal(completion.completion_tokens) * model["output_price_per_1k"]) / Decimal(1000)
            attempt.update(status="completed", model=completion.model, prompt_tokens=completion.prompt_tokens,
                           completion_tokens=completion.completion_tokens, cost_usd=cost,
                           usage_details={"usage_known": True, "reported": completion.usage_details, "pricing": "configured_standard_rates_no_cache_adjustment", "temperature_sent": temperature is not None, "max_tokens": tokens})
            return completion
        except (LookupError, ValueError):
            attempt["error_code"] = "credential_unavailable"
            attempt["cost_usd"] = Decimal(0)
            attempt["usage_details"] = {"usage_known": True, "provider_called": False}
            raise providers.ProviderFailure("credential_unavailable") from None
        except providers.ProviderFailure as error:
            attempt["error_code"] = error.code
            if error.status:
                attempt["usage_details"]["upstream_status"] = error.status
            raise
        except asyncio.CancelledError:
            attempt["error_code"] = "request_cancelled"
            raise
        finally:
            attempt["latency_ms"] = round((perf_counter() - call_started) * 1000)
            attempts.append(attempt)

    failure: providers.ProviderFailure | None = None
    try:
        while True:
            result = await call("answer", messages, request.max_tokens)
            if model["tier"] == models[-1]["tier"]:
                score = 1.0
            else:
                checked = await call("self_check", [
                    {"role": "system", "content": "Rate from 0 to 10 how confident you are that the answer is correct and complete. Reply with only the integer."},
                    {"role": "user", "content": f"Question:\n{question}\n\nAnswer:\n{result.content}"},
                ], model["self_check_max_tokens"])
                try:
                    rating = int(checked.content.strip())
                    parsed = 0 <= rating <= 10
                except ValueError:
                    rating, parsed = 5, False
                self_score = rating / 10 if parsed else 0.5
                attempts[-1]["usage_details"]["self_check"] = {"score": self_score, "parse_status": "parsed" if parsed else "neutral_fallback"}
                score = 0.5 * heuristic_confidence(question, result.content) + 0.5 * self_score
            index = next(index for index, item in enumerate(models) if item["tier"] == model["tier"])
            if forced or score >= settings.confidence_threshold or escalations >= settings.max_escalations or index == len(models) - 1:
                break
            next_model = models[index + 1]
            reason += f" Confidence {score:.2f} below {settings.confidence_threshold:.2f}; escalating {model['tier']} to {next_model['tier']}."
            model = next_model
            escalations += 1
        if not result.content.strip():
            raise providers.ProviderFailure("empty_provider_answer")
    except providers.ProviderFailure as error:
        failure = error
    except asyncio.CancelledError:
        failure = providers.ProviderFailure("request_cancelled")
    latency = round((perf_counter() - started) * 1000)
    known_cost = sum((attempt["cost_usd"] or Decimal(0)) for attempt in attempts)
    complete_cost = known_cost if all(attempt["cost_usd"] is not None for attempt in attempts) else None
    final_tokens = (result.prompt_tokens, result.completion_tokens) if result and not failure else (0, 0)
    reference = (Decimal(final_tokens[0]) * Decimal(str(settings.reference_input_price_per_1k)) + Decimal(final_tokens[1]) * Decimal(str(settings.reference_output_price_per_1k))) / Decimal(1000)
    row = {
        "id": request_id, "created_at": created, "status": "failed" if failure else "completed",
        "error_code": failure.code if failure else None, "prompt_preview": " ".join(question.split())[:200],
        "messages": messages, "answer": result.content if result and not failure else "", "features": features,
        "tier_chosen": chosen, "tier_final": model["tier"], "provider": model["provider"],
        "model": result.model if result and not failure else model["model"], "escalated": escalations > 0,
        "confidence": score, "reason": failure.code if failure else reason, "routing_mode": mode,
        "prompt_tokens": final_tokens[0], "completion_tokens": final_tokens[1], "latency_ms": latency,
        "actual_cost_usd": complete_cost, "reference_cost_usd": reference, "source": source,
    }
    await asyncio.shield(run_in_threadpool(store.record_inference, actor, row, attempts))
    if failure:
        if failure.code == "request_cancelled":
            raise asyncio.CancelledError()
        raise RoutingFailure(f"Provider request failed ({failure.code}). See the request history for recorded attempts.", 504 if failure.code == "provider_timeout" else 502, request_id)
    return ChatCompletionResponse(
        id=request_id, created=int(created.timestamp()), model=result.model,
        choices=[Choice(message=ChatMessage(role="assistant", content=result.content), finish_reason=result.finish_reason)],
        usage=Usage(prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens, total_tokens=result.prompt_tokens + result.completion_tokens),
        smartroute=RoutingInfo(request_id=request_id, tier_chosen=chosen, tier_final=model["tier"], escalated=escalations > 0,
            confidence=score, reason=reason, routing_mode=mode, latency_ms=latency, actual_cost_usd=float(complete_cost), reference_cost_usd=float(reference)),
    )