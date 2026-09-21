"""Verify feedback submission and the complete feedback-to-learned-routing workflow."""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app import db, train as training
from app.config import Tier
from app.providers.base import ProviderResult
from app.routing import router as routing_router
from app.schemas import ChatCompletionRequest


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Generate synthetic answers only inside the test's isolated request database."""
    def answer(
        tier: Tier, _request: ChatCompletionRequest, _messages: list[dict[str, str]]
    ) -> ProviderResult:
        """Return an answer naming the model actually selected by routing."""
        return ProviderResult("A test answer.", 10, 3, 5, tier.model)

    mocked = AsyncMock(side_effect=answer)
    monkeypatch.setattr(routing_router, "_call_tier", mocked)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=1.0))
    return mocked


@pytest.mark.asyncio
@pytest.mark.parametrize(("score", "note"), [(1, "Helpful"), (-1, "Needs detail"), (1, None)])
async def test_submit_feedback(
    client: httpx.AsyncClient, provider: AsyncMock, score: int, note: str | None
) -> None:
    """A submitted rating is returned and stored on the original request."""
    completion = await client.post("/v1/chat/completions", json={
        "model": "smartroute/small", "messages": [{"role": "user", "content": "Hello"}],
    })
    assert completion.status_code == 200
    request_id = completion.json()["id"]
    payload = {"request_id": request_id, "score": score, "note": note}

    response = await client.post("/v1/feedback", json=payload)

    assert response.status_code == 200
    assert response.json() == payload
    stored = db.get_request(request_id)
    assert stored is not None
    assert stored["feedback"] == score
    assert stored["feedback_note"] == note
    assert len(db.rows_for_training()) == 1


@pytest.mark.asyncio
async def test_feedback_can_be_replaced(client: httpx.AsyncClient, provider: AsyncMock) -> None:
    """Replacing feedback updates the same row and clears an omitted note."""
    completion = await client.post("/v1/chat/completions", json={
        "model": "smartroute/small", "messages": [{"role": "user", "content": "Hello"}],
    })
    request_id = completion.json()["id"]
    first = await client.post("/v1/feedback", json={
        "request_id": request_id, "score": 1, "note": "Initial rating",
    })
    second = await client.post("/v1/feedback", json={"request_id": request_id, "score": -1})

    assert first.status_code == second.status_code == 200
    assert second.json()["note"] is None
    stored = db.get_request(request_id)
    assert stored is not None and stored["feedback"] == -1
    assert stored["feedback_note"] is None
    assert len(db.rows_for_training()) == 1


@pytest.mark.asyncio
async def test_unknown_feedback_request(client: httpx.AsyncClient) -> None:
    """Feedback cannot create or invent a request record."""
    response = await client.post("/v1/feedback", json={"request_id": "missing", "score": 1})

    assert response.status_code == 404
    assert db.rows_for_training() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {}, {"request_id": "missing"}, {"request_id": "", "score": 1},
    {"request_id": "missing", "score": 0}, {"request_id": "missing", "score": 2},
    {"request_id": "missing", "score": -2}, {"request_id": "missing", "score": True},
    {"request_id": "missing", "score": 1.0}, {"request_id": "missing", "score": "1"},
    {"request_id": "missing", "score": 1, "note": 123},
])
async def test_invalid_feedback(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    """Only nonempty IDs, integer positive/negative scores, and text notes are accepted."""
    response = await client.post("/v1/feedback", json=payload)

    assert response.status_code == 422
    assert db.rows_for_training() == []


@pytest.mark.asyncio
async def test_feedback_to_training_to_routing(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Learn from real API-persisted test ratings and use the saved model on the next chat."""
    examples = [
        ("small", "Hello", 1),
        ("small", "Explain Python code", -1),
        ("medium", "Write a comprehensive essay", -1),
    ]
    for tier, prompt, score in examples:
        for index in range(10):
            response = await client.post("/v1/chat/completions", json={
                "model": f"smartroute/{tier}",
                "messages": [{"role": "user", "content": f"{prompt} {index}"}],
            })
            assert response.status_code == 200
            feedback = await client.post("/v1/feedback", json={
                "request_id": response.json()["id"], "score": score,
            })
            assert feedback.status_code == 200

    result = training.train()

    assert result["trained"] is True
    assert result["n_rows"] == 30
    assert result["classes"] == ["large", "medium", "small"]
    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello 1"}],
    })
    assert response.status_code == 200
    routing = response.json()["smartroute"]
    assert routing["routing_mode"] == "learned"
    assert routing["tier_chosen"] == routing["tier_final"] == "small"
    assert "probability" in routing["reason"]
    assert routing["confidence"] == 1.0
    assert db.list_requests()["total"] == 31