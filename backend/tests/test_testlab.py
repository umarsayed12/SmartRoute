"""Verify the benchmark suite, sequential runs, history, and summary calculations."""

import asyncio
from collections import Counter
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import db
from app.api import testlab
from app.config import Tier
from app.providers.base import ProviderResult
from app.routing import router as routing_router
from app.schemas import ChatCompletionRequest


def test_default_prompt_suite() -> None:
    """The built-in suite contains exactly 40 distinct prompts with the required mix."""
    prompts = testlab.load_suite()

    assert len(prompts) == len({prompt.id for prompt in prompts}) == 40
    assert Counter(prompt.expected_tier for prompt in prompts) == {"small": 15, "medium": 15, "large": 10}
    assert all(prompt.prompt.strip() and prompt.category.strip() for prompt in prompts)
    assert max(len(prompt.prompt.split()) for prompt in prompts if prompt.category == "coding") > 200
    assert testlab.get_suites()[0]["count"] == 40


@pytest.mark.parametrize("content", [
    "", "not json", '{"id":"incomplete"}',
    '{"id":"same","prompt":"Hello","expected_tier":"small","category":"greeting"}\n'
    '{"id":"same","prompt":"Hi","expected_tier":"small","category":"greeting"}',
])
def test_invalid_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """Malformed or duplicate suite data produces a controlled server error."""
    path = tmp_path / "prompts.jsonl"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(testlab, "SUITE_PATH", path)

    with pytest.raises(HTTPException) as caught:
        testlab.load_suite()

    assert caught.value.status_code == 500


@pytest.mark.parametrize("payload", [
    {"suite": "../other"}, {"mode": "invalid"}, {"limit": 0}, {"limit": 41},
    {"limit": True}, {"limit": "2"},
])
def test_invalid_run_options(payload: dict[str, object]) -> None:
    """Reject arbitrary paths, unsupported modes, and invalid run limits."""
    with pytest.raises(ValidationError):
        testlab.SuiteRunRequest(**payload)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub only inference, retaining real routing, completion construction, and request logging."""
    async def answer(
        tier: Tier, request: ChatCompletionRequest, _messages: list[dict[str, str]]
    ) -> ProviderResult:
        """Return synthetic tokens with the actual selected model."""
        assert request.max_tokens == 256
        return ProviderResult("A benchmark answer.", 20, 10, 5, tier.model)

    mocked = AsyncMock(side_effect=answer)
    monkeypatch.setattr(routing_router, "_call_tier", mocked)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=1.0))
    monkeypatch.setattr(routing_router.settings, "LARGE_MODEL", "")
    return mocked


@pytest.mark.asyncio
async def test_suite_listing(client: httpx.AsyncClient) -> None:
    """Expose suite metadata and the same output budget used during execution."""
    response = await client.get("/v1/testlab/suites")

    assert response.status_code == 200
    assert response.json() == [{
        "id": "default", "name": "Default", "count": 40,
        "tier_distribution": {"small": 15, "medium": 15, "large": 10}, "max_tokens": 256,
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "tier", "matches"), [
    ("auto", "small", True), ("small", "small", True),
    ("medium", "medium", False), ("large", "medium", False),
])
async def test_run_modes_and_logging(
    client: httpx.AsyncClient, provider: AsyncMock, mode: str, tier: str, matches: bool
) -> None:
    """Every run mode goes through the normal gateway and logs one row per prompt."""
    response = await client.post("/v1/testlab/run", json={"mode": mode, "limit": 2})

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"].startswith("testlab-")
    assert data["suite"] == "default"
    assert data["mode"] == mode
    assert data["prompt_count"] == 2
    assert [result["id"] for result in data["results"]] == ["simple-01", "simple-02"]
    assert all(result["tier_final"] == tier and result["match"] is matches for result in data["results"])
    assert data["summary"]["routing_accuracy"] == float(matches)
    assert data["summary"]["escalation_rate"] == 0
    assert data["summary"]["total_actual_usd"] == 0
    assert data["summary"]["total_reference_usd"] == pytest.approx(0.0003)
    assert data["summary"]["saved_pct"] == 100
    assert provider.await_count == 2
    assert db.list_requests()["total"] == 2
    for result in data["results"]:
        stored = db.get_request(result["request_id"])
        assert stored is not None and stored["source"] == "testlab"
        assert stored["tier_final"] == tier
        assert stored["routing_mode"] == ("heuristic" if mode == "auto" else "forced")
    history = await client.get("/v1/testlab/runs")
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["run_id"] == data["run_id"]
    assert history.json()["items"][0]["summary"] == data["summary"]
    assert "results" not in history.json()["items"][0]


@pytest.mark.asyncio
async def test_full_default_suite(client: httpx.AsyncClient, provider: AsyncMock) -> None:
    """An omitted limit runs all 40 prompts and retains literal large-fallback mismatches."""
    response = await client.post("/v1/testlab/run", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["prompt_count"] == len(data["results"]) == 40
    assert [result["id"] for result in data["results"]] == [prompt.id for prompt in testlab.load_suite()]
    assert provider.await_count == db.list_requests()["total"] == 40
    hard_results = [result for result in data["results"] if result["expected_tier"] == "large"]
    assert len(hard_results) == 10
    assert all(not result["match"] for result in hard_results)
    assert db.list_testlab_runs()["items"][0]["prompt_count"] == 40


def test_summary_calculations() -> None:
    """Use result-level match and escalation flags and retain negative savings."""
    results = [
        {"match": True, "escalated": False, "latency_ms": 10, "actual_cost_usd": 2, "reference_cost_usd": 1},
        {"match": False, "escalated": True, "latency_ms": 30, "actual_cost_usd": 4, "reference_cost_usd": 2},
    ]

    assert testlab._summarize(results) == {
        "routing_accuracy": 0.5, "escalation_rate": 0.5, "avg_latency_ms": 20,
        "total_actual_usd": 6, "total_reference_usd": 3, "saved_pct": -100,
    }
    assert all(value == 0 for value in testlab._summarize([]).values())
    results[0]["reference_cost_usd"] = results[1]["reference_cost_usd"] = 0
    assert testlab._summarize(results)["saved_pct"] == 0


@pytest.mark.asyncio
async def test_runs_are_sequential_and_reject_overlap(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Pause the first inference to verify another run cannot overlap it or reorder prompts."""
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def answer(
        tier: Tier, request: ChatCompletionRequest, _messages: list[dict[str, str]]
    ) -> ProviderResult:
        """Hold the first call until the test has checked in-flight state."""
        calls.append(request.messages[0].content)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return ProviderResult("Answer", 10, 2, 5, tier.model)

    provider.side_effect = answer
    running = asyncio.create_task(client.post("/v1/testlab/run", json={"limit": 2}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert calls == ["Hello!"]
        overlapping = await client.post("/v1/testlab/run", json={"limit": 1})
        assert overlapping.status_code == 409
    finally:
        release.set()
        completed = await asyncio.wait_for(running, timeout=5)

    assert completed.status_code == 200
    assert calls == ["Hello!", "Good morning. Reply with a brief greeting."]


@pytest.mark.asyncio
async def test_failed_run_keeps_partial_requests_and_releases_lock(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Retain completed requests but not a misleading successful summary after failure."""
    provider.side_effect = [
        ProviderResult("Answer", 10, 2, 5, "test-model"),
        httpx.ConnectError("private provider detail"),
    ]

    response = await client.post("/v1/testlab/run", json={"limit": 2})

    assert response.status_code == 503
    assert "simple-02" in response.json()["detail"]
    assert "1 completed" in response.json()["detail"]
    assert "private provider detail" not in response.text
    assert db.list_requests()["total"] == 1
    assert db.list_testlab_runs()["total"] == 0
    provider.side_effect = None
    provider.return_value = ProviderResult("Answer", 10, 2, 5, "test-model")
    retry = await client.post("/v1/testlab/run", json={"limit": 1})
    assert retry.status_code == 200
    assert db.list_testlab_runs()["total"] == 1


@pytest.mark.asyncio
async def test_run_history_pagination(client: httpx.AsyncClient, provider: AsyncMock) -> None:
    """Keep summaries across reinitialization and expose an accurate paginated total."""
    first = await client.post("/v1/testlab/run", json={"limit": 1})
    second = await client.post("/v1/testlab/run", json={"limit": 1})
    db.init_db()

    page = await client.get("/v1/testlab/runs", params={"limit": 1, "offset": 1})

    assert first.status_code == second.status_code == page.status_code == 200
    assert first.json()["run_id"] != second.json()["run_id"]
    assert page.json()["total"] == 2
    assert page.json()["items"][0]["run_id"] == first.json()["run_id"]
    empty = await client.get("/v1/testlab/runs", params={"offset": 10})
    assert empty.json()["items"] == [] and empty.json()["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"suite": "unknown"}, {"limit": 0}, {"mode": "bad"}])
async def test_invalid_run_api(
    client: httpx.AsyncClient, provider: AsyncMock, payload: dict[str, object]
) -> None:
    """Reject invalid runs before any inference or history writes."""
    response = await client.post("/v1/testlab/run", json=payload)

    assert response.status_code == 422
    provider.assert_not_awaited()
    assert db.list_testlab_runs()["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_invalid_history_pagination(client: httpx.AsyncClient, parameters: dict[str, int]) -> None:
    """Reject invalid history page sizes and offsets."""
    response = await client.get("/v1/testlab/runs", params=parameters)

    assert response.status_code == 422