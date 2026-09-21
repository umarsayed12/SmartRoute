"""Analyze a request, select a tier, and return its answer and routing details."""

from uuid import uuid4

from app.config import settings
from app.providers import ollama, openai_compatible
from app.providers.base import ProviderResult
from app.routing.features import extract_features
from app.routing.heuristic import pick_tier
from app.schemas import ChatCompletionRequest, RoutingInfo


async def route_and_answer(
    request: ChatCompletionRequest,
) -> tuple[ProviderResult, RoutingInfo]:
    """Apply heuristic routing and call the resolved tier exactly once."""
    request_id = f"chatcmpl-{uuid4().hex}"
    messages = [message.model_dump() for message in request.messages]
    chosen_tier, reason = pick_tier(extract_features(messages))
    tier = settings.get_tier(chosen_tier)
    if tier.name != chosen_tier:
        reason += f" {chosen_tier.capitalize()} is disabled; using {tier.name} instead."

    if tier.provider == "ollama":
        result = await ollama.chat(
            model=tier.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=tier.base_url,
        )
    else:
        result = await openai_compatible.chat(
            model=tier.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=tier.base_url,
            api_key=tier.api_key.get_secret_value(),
        )

    routing = RoutingInfo(
        request_id=request_id,
        tier_chosen=chosen_tier,
        tier_final=tier.name,
        escalated=False,
        confidence=None,
        reason=reason,
        routing_mode="heuristic",
        latency_ms=result.latency_ms,
        actual_cost_usd=(
            result.prompt_tokens * tier.input_price_per_1k
            + result.completion_tokens * tier.output_price_per_1k
        ) / 1000,
        reference_cost_usd=(
            result.prompt_tokens * settings.REFERENCE_INPUT_PRICE_PER_1K
            + result.completion_tokens * settings.REFERENCE_OUTPUT_PRICE_PER_1K
        ) / 1000,
    )
    return result, routing