"""Chat, feedback, and routing schemas for the SmartRoute API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """Represent a text message in a chat conversation."""

    role: str = Field(min_length=1)
    content: str


class ChatCompletionRequest(BaseModel):
    """Accept the supported non-streaming chat completion parameters."""

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False


class Usage(BaseModel):
    """Report provider token counts in the OpenAI completion format."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class Choice(BaseModel):
    """Wrap a generated assistant message as one completion choice."""

    index: int = 0
    message: ChatMessage
    finish_reason: Literal["stop", "length"] = "stop"


class RoutingInfo(BaseModel):
    """Expose tier selection, confidence signals, total timing, and costs."""

    request_id: str
    tier_chosen: str
    tier_final: str
    escalated: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    routing_mode: str
    latency_ms: int = Field(ge=0)
    actual_cost_usd: float = Field(ge=0)
    reference_cost_usd: float = Field(ge=0)


class ChatCompletionResponse(BaseModel):
    """Return an SDK-compatible completion plus SmartRoute-specific details."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
    smartroute: RoutingInfo


class FeedbackRequest(BaseModel):
    """Attach a positive or negative integer rating to a completed request."""

    request_id: str = Field(min_length=1)
    score: int = Field(strict=True, ge=-1, le=1)
    note: str | None = None

    @field_validator("score")
    @classmethod
    def validate_score(cls, score: int) -> int:
        """Reject zero so feedback always represents a positive or negative rating."""
        if score == 0:
            raise ValueError("Feedback score must be -1 or 1.")
        return score