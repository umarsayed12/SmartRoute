"""Serve non-streaming OpenAI-compatible completions using the small tier."""

from time import time
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.providers import ollama
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    RoutingInfo,
    Usage,
)

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Forward every supported request to small and build an OpenAI response."""
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported yet.")

    tier = settings.get_tier("small")
    request_id = f"chatcmpl-{uuid4().hex}"
    created = int(time())
    try:
        result = await ollama.chat(
            model=tier.model,
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=tier.base_url,
        )
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="Model provider timed out.") from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail="Model provider is unavailable. Check that Ollama is running.",
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail="Model provider rejected the request. Check that the model is installed.",
        ) from error

    return ChatCompletionResponse(
        id=request_id,
        created=created,
        model=result.model,
        choices=[Choice(message=ChatMessage(role="assistant", content=result.content))],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        smartroute=RoutingInfo(
            request_id=request_id,
            tier_chosen=tier.name,
            tier_final=tier.name,
            escalated=False,
            confidence=None,
            reason="Single-tier mode: all requests use small; confidence is not scored yet.",
            routing_mode="single_tier",
            latency_ms=result.latency_ms,
            actual_cost_usd=(
                result.prompt_tokens * tier.input_price_per_1k
                + result.completion_tokens * tier.output_price_per_1k
            ) / 1000,
            reference_cost_usd=(
                result.prompt_tokens * settings.REFERENCE_INPUT_PRICE_PER_1K
                + result.completion_tokens * settings.REFERENCE_OUTPUT_PRICE_PER_1K
            ) / 1000,
        ),
    )