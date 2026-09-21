"""Serve OpenAI-compatible completions and queue their full routing records."""

import json
from datetime import datetime, timezone
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app import db
from app.routing.features import extract_features
from app.routing.router import LearnedRouterUnavailableError, route_and_answer
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    Usage,
)

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    source: Annotated[
        Literal["api", "playground", "testlab", "sdk"], Header(alias="X-SmartRoute-Source")
    ] = "api",
) -> ChatCompletionResponse:
    """Route a request, return its completion, and log it after the response."""
    if request.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported yet.")

    created_at = datetime.now(timezone.utc)
    try:
        result, routing = await route_and_answer(request)
    except LearnedRouterUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
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

    response = ChatCompletionResponse(
        id=routing.request_id,
        created=int(created_at.timestamp()),
        model=result.model,
        choices=[Choice(message=ChatMessage(role="assistant", content=result.content))],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        smartroute=routing,
    )
    messages = [message.model_dump() for message in request.messages]
    latest_prompt = next(
        (message["content"] for message in reversed(messages) if message["role"] == "user"),
        messages[-1]["content"],
    )
    background_tasks.add_task(db.insert_request, {
        "id": routing.request_id,
        "created_at": created_at.isoformat(),
        "prompt_preview": " ".join(latest_prompt.split())[:200],
        "prompt_full": json.dumps(messages, ensure_ascii=False),
        "answer_full": result.content,
        "features_json": json.dumps(extract_features(messages)),
        **routing.model_dump(exclude={"request_id"}),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "source": source,
    })
    return response