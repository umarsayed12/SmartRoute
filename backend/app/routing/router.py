"""Route chat requests with confidence checks, bounded escalation, and total costs."""

from time import perf_counter
from uuid import uuid4

from app.config import Tier, settings
from app.providers import ollama, openai_compatible
from app.providers.base import ProviderResult
from app.routing import learned
from app.routing.confidence import score
from app.routing.features import extract_features
from app.routing.heuristic import pick_tier
from app.schemas import ChatCompletionRequest, RoutingInfo


class LearnedRouterUnavailableError(RuntimeError):
    """Signal that learned-only routing was requested without a usable classifier."""


async def _call_tier(
    tier: Tier, request: ChatCompletionRequest, messages: list[dict[str, str]]
) -> ProviderResult:
    """Dispatch one answer request to the configured tier's provider."""
    if tier.provider == "ollama":
        return await ollama.chat(
            model=tier.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=tier.base_url,
        )
    return await openai_compatible.chat(
        model=tier.model,
        messages=messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        base_url=tier.base_url,
        api_key=tier.api_key.get_secret_value(),
    )


async def route_and_answer(
    request: ChatCompletionRequest,
) -> tuple[ProviderResult, RoutingInfo]:
    """Choose an initial tier, score its answer, and optionally cascade upward."""
    started = perf_counter()
    request_id = f"chatcmpl-{uuid4().hex}"
    messages = [message.model_dump() for message in request.messages]
    chosen_tier = request.model.removeprefix("smartroute/")
    forced = request.model.startswith("smartroute/") and chosen_tier in {
        "small", "medium", "large",
    }
    if forced:
        reason = f"Forced {chosen_tier} tier."
        routing_mode = "forced"
    else:
        features = extract_features(messages)
        preference = settings.ROUTING_MODE_PREFERENCE
        prediction = None if preference == "heuristic_only" else learned.pick_tier(features)
        if prediction is None:
            if preference == "learned_only":
                raise LearnedRouterUnavailableError("Learned-only routing requires a usable trained model.")
            chosen_tier, reason = pick_tier(features)
            routing_mode = "heuristic"
        else:
            chosen_tier, _probability, reason = prediction
            routing_mode = "learned"
    tier = settings.get_tier(chosen_tier)
    if tier.name != chosen_tier:
        reason += f" {chosen_tier.capitalize()} is disabled; using {tier.name} instead."

    enabled_tiers = [configured for configured in settings.TIERS if configured.enabled]
    tier_index = next(
        index for index, configured in enumerate(enabled_tiers) if configured.name == tier.name
    )
    question = next(
        (message["content"] for message in reversed(messages) if message["role"] == "user"),
        messages[-1]["content"],
    )
    escalations = 0
    actual_cost_usd = 0.0
    while True:
        result = await _call_tier(tier, request, messages)
        actual_cost_usd += (
            result.prompt_tokens * tier.input_price_per_1k
            + result.completion_tokens * tier.output_price_per_1k
        ) / 1000
        answer_confidence = await score(question, result.content, tier)
        if forced or answer_confidence >= settings.CONFIDENCE_THRESHOLD:
            break
        if tier_index + 1 == len(enabled_tiers):
            break
        if escalations >= settings.MAX_ESCALATIONS:
            reason += " Escalation limit reached."
            break
        next_tier = enabled_tiers[tier_index + 1]
        reason += (
            f" Confidence {answer_confidence:.2f} below {settings.CONFIDENCE_THRESHOLD:.2f};"
            f" escalating {tier.name} to {next_tier.name}."
        )
        tier = next_tier
        tier_index += 1
        escalations += 1

    routing = RoutingInfo(
        request_id=request_id,
        tier_chosen=chosen_tier,
        tier_final=tier.name,
        escalated=escalations > 0,
        confidence=answer_confidence,
        reason=reason,
        routing_mode=routing_mode,
        latency_ms=round((perf_counter() - started) * 1000),
        actual_cost_usd=actual_cost_usd,
        reference_cost_usd=(
            result.prompt_tokens * settings.REFERENCE_INPUT_PRICE_PER_1K
            + result.completion_tokens * settings.REFERENCE_OUTPUT_PRICE_PER_1K
        ) / 1000,
    )
    return result, routing