"""Serve non-streaming OpenAI-compatible completions through the tier router."""

from time import time

import httpx
from fastapi import APIRouter, HTTPException

from app.routing.router import route_and_answer
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Route a supported request and return an OpenAI-shaped completion."""
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported yet.")

    created = int(time())
    try:
        result, routing = await route_and_answer(request)
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="Model provider timed out.") from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail="Model provider is unavailable. Check the configured endpoint.",
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail="Model provider rejected the request. Check its model and credentials.",
        ) from error

    return ChatCompletionResponse(
        id=routing.request_id,
        created=created,
        model=result.model,
        choices=[Choice(message=ChatMessage(role="assistant", content=result.content))],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        smartroute=routing,
    )