"""Verify request persistence, history filters, and dashboard aggregates."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from app import db
from app.api import stats


@pytest.fixture(autouse=True)
def initialized_database(isolated_database: Path) -> None:
    """Create a fresh request table before each database test."""
    db.init_db()


def _row(**changes: Any) -> dict[str, Any]:
    """Build a complete synthetic request row with configurable test fields."""
    return {
        "id": "chatcmpl-first",
        "created_at": "2026-09-21T10:00:00+00:00",
        "prompt_preview": "Hello",
        "prompt_full": json.dumps([{"role": "user", "content": "Hello"}]),
        "answer_full": "Hello!",
        "features_json": json.dumps({"prompt_words": 1.0}),
        "tier_chosen": "small",
        "tier_final": "small",
        "escalated": False,
        "confidence": 0.9,
        "reason": "A short prompt.",
        "routing_mode": "heuristic",
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "latency_ms": 25,
        "actual_cost_usd": 0.0,
        "reference_cost_usd": 0.000045,
        **changes,
    }


def test_init_preserves_rows_and_enables_wal(isolated_database: Path) -> None:
    """Repeated startup keeps existing data and uses WAL journal mode."""
    db.insert_request(_row())
    db.init_db()

    assert db.get_request("chatcmpl-first") is not None
    with closing(sqlite3.connect(isolated_database)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_init_creates_parent_directory(
    isolated_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured database can live in a directory that does not yet exist."""
    path = isolated_database.parent / "nested" / "requests.db"
    monkeypatch.setattr(db.settings, "DB_PATH", path)

    db.init_db()

    assert path.is_file()


def test_request_round_trip() -> None:
    """Preserve complete JSON, Unicode, routing details, and nullable feedback."""
    prompt = [{"role": "user", "content": "caf\u00e9 '; DROP TABLE requests; --"}]
    row = _row(prompt_full=json.dumps(prompt, ensure_ascii=False), escalated=True)
    db.insert_request(row)

    stored = db.get_request(row["id"])

    assert stored is not None
    assert json.loads(stored["prompt_full"]) == prompt
    assert json.loads(stored["features_json"]) == {"prompt_words": 1.0}
    assert stored["escalated"] is True
    assert stored["source"] == "api"
    assert stored["feedback"] is None
    assert stored["feedback_note"] is None
    assert stored["reference_cost_usd"] == row["reference_cost_usd"]
    assert db.get_request("missing") is None


@pytest.fixture
def requests_with_feedback() -> None:
    """Populate rows that distinguish chosen/final tiers and all feedback states."""
    db.insert_request(_row(
        id="first", tier_final="medium", escalated=True, feedback=-1,
        prompt_full='[{"role":"user","content":"A Python question"}]',
        answer_full="The answer includes 100%.",
    ))
    db.insert_request(_row(
        id="second", created_at="2026-09-21T11:00:00+00:00",
        tier_chosen="large", tier_final="medium", source="playground",
    ))
    db.insert_request(_row(
        id="third", created_at="2026-09-21T12:00:00+00:00", feedback=1,
        answer_full="Use an_under_score literally.",
    ))


@pytest.mark.parametrize(("filters", "expected"), [
    ({}, ["third", "second", "first"]),
    ({"tier": "medium"}, ["second", "first"]),
    ({"tier": "large"}, []),
    ({"escalated": True}, ["first"]),
    ({"escalated": False}, ["third", "second"]),
    ({"feedback": -1}, ["first"]),
    ({"feedback": 1}, ["third"]),
    ({"feedback": 0}, ["second"]),
    ({"search": "PYTHON"}, ["first"]),
    ({"search": "%"}, ["first"]),
    ({"search": "_"}, ["third"]),
    ({"search": "' OR 1=1 --"}, []),
    ({"source": "api"}, ["third", "first"]),
    ({"source": "playground"}, ["second"]),
    ({"source": "sdk"}, []),
    ({"source": "testlab"}, []),
    ({"tier": "medium", "escalated": False, "feedback": 0}, ["second"]),
])
def test_request_filters(
    requests_with_feedback: None, filters: dict[str, Any], expected: list[str]
) -> None:
    """Combine filters safely, including false flags and literal search punctuation."""
    page = db.list_requests(**filters)

    assert [row["id"] for row in page["items"]] == expected
    assert page["total"] == len(expected)
    assert all("prompt_full" not in row for row in page["items"])
    assert all("answer_full" not in row for row in page["items"])
    assert all("features_json" not in row for row in page["items"])


def test_pagination_totals(requests_with_feedback: None) -> None:
    """Count all filtered rows even when the requested page is partial or empty."""
    page = db.list_requests(limit=1, offset=1, tier="medium")
    empty = db.list_requests(limit=1, offset=3, tier="medium")

    assert page["total"] == empty["total"] == 2
    assert page["limit"] == page["offset"] == 1
    assert [row["id"] for row in page["items"]] == ["first"]
    assert empty["items"] == []


def test_identical_timestamps_have_stable_order() -> None:
    """The ID breaks timestamp ties so offset pagination has a stable order."""
    db.insert_request(_row(id="first"))
    db.insert_request(_row(id="second"))

    assert db.list_requests(limit=1)["items"][0]["id"] == "second"
    assert db.list_requests(limit=1, offset=1)["items"][0]["id"] == "first"


def test_feedback_and_training_rows(requests_with_feedback: None) -> None:
    """Only rated records are training candidates, and feedback can be replaced."""
    assert [row["id"] for row in db.rows_for_training()] == ["first", "third"]
    assert db.set_feedback("second", 1, "Helpful") is True
    assert db.get_request("second")["feedback_note"] == "Helpful"
    assert db.set_feedback("second", -1) is True
    assert db.get_request("second")["feedback"] == -1
    assert db.get_request("second")["feedback_note"] is None
    assert len(db.rows_for_training()) == 3
    assert db.set_feedback("missing", 1) is False
    with pytest.raises(ValueError, match="Feedback score"):
        db.set_feedback("second", 0)


@pytest.mark.parametrize("filters", [
    {"limit": 0}, {"limit": 101}, {"offset": -1}, {"tier": "unknown"}, {"feedback": 2},
    {"source": "unknown"},
])
def test_invalid_filters(filters: dict[str, Any]) -> None:
    """Invalid pagination and filter values fail before executing a query."""
    with pytest.raises(ValueError):
        db.list_requests(**filters)


def test_concurrent_inserts() -> None:
    """Independent worker-thread connections can log requests without losing rows."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda index: db.insert_request(_row(id=f"request-{index}")), range(8)))

    assert db.list_requests()["total"] == 8


@pytest.mark.asyncio
async def test_history_list_and_detail(
    client: httpx.AsyncClient, requests_with_feedback: None
) -> None:
    """Expose paginated summaries separately from full request content."""
    response = await client.get("/v1/requests", params={
        "tier": "medium", "limit": 1, "offset": 1,
    })

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert page["limit"] == page["offset"] == 1
    assert [row["id"] for row in page["items"]] == ["first"]
    assert "prompt_full" not in page["items"][0]
    assert "answer_full" not in page["items"][0]
    assert "features_json" not in page["items"][0]

    detail = await client.get("/v1/requests/first")
    assert detail.status_code == 200
    assert json.loads(detail.json()["prompt_full"])[0]["content"] == "A Python question"
    assert detail.json()["answer_full"] == "The answer includes 100%."
    assert detail.json()["escalated"] is True


@pytest.mark.asyncio
async def test_history_combined_filters(
    client: httpx.AsyncClient, requests_with_feedback: None
) -> None:
    """Parse false booleans and unrated feedback filters from HTTP query strings."""
    response = await client.get("/v1/requests", params={
        "tier": "medium", "escalated": "false", "feedback": "0", "search": "hello", "source": "playground",
    })

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "second"


@pytest.mark.asyncio
async def test_empty_history_and_unknown_id(client: httpx.AsyncClient) -> None:
    """A fresh database has a valid empty page and missing records return 404."""
    response = await client.get("/v1/requests")

    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    missing = await client.get("/v1/requests/missing")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Request not found."


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [
    {"limit": "0"}, {"limit": "101"}, {"offset": "-1"}, {"tier": "unknown"},
    {"escalated": "maybe"}, {"feedback": "2"}, {"feedback": "bad"},
    {"source": "unknown"},
])
async def test_history_query_validation(
    client: httpx.AsyncClient, parameters: dict[str, str]
) -> None:
    """Reject invalid query values before reaching the SQLite helpers."""
    response = await client.get("/v1/requests", params=parameters)

    assert response.status_code == 422


@pytest.fixture
def stats_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix the dashboard clock so calendar boundaries do not depend on the test date."""
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(stats, "datetime", clock)


@pytest.mark.asyncio
async def test_empty_dashboard(client: httpx.AsyncClient, stats_clock: None) -> None:
    """Empty periods have zero totals, nullable quality/latency, and every calendar day."""
    response = await client.get("/v1/stats", params={"days": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["totals"] == {"requests": 0, "escalations": 0, "escalation_rate": 0}
    assert data["cost"] == {"actual_usd": 0, "reference_usd": 0, "saved_usd": 0, "saved_pct": 0}
    assert data["quality"]["feedback_count"] == 0
    assert data["quality"]["positive_rate"] is None
    assert data["tier_distribution"] == {"small": 0, "medium": 0, "large": 0}
    assert data["routing_modes"] == {"heuristic": 0, "learned": 0, "forced": 0}
    assert data["latency"]["small"] == {"p50": None, "p95": None}
    assert [point["date"] for point in data["timeline"]] == [
        "2026-09-19", "2026-09-20", "2026-09-21",
    ]
    assert all(point["requests"] == 0 and point["positive_rate"] is None for point in data["timeline"])


@pytest.mark.asyncio
async def test_dashboard_aggregates(client: httpx.AsyncClient, stats_clock: None) -> None:
    """Aggregate costs, rated-only quality, routing modes, daily data, and latency percentiles."""
    db.insert_request(_row(
        id="small-positive", created_at="2026-09-20T09:00:00+00:00",
        actual_cost_usd=1, reference_cost_usd=4, latency_ms=10, feedback=1,
    ))
    db.insert_request(_row(
        id="small-negative", created_at="2026-09-21T09:00:00+00:00",
        actual_cost_usd=2, reference_cost_usd=6, latency_ms=30, feedback=-1, routing_mode="forced",
    ))
    db.insert_request(_row(
        id="medium", tier_final="medium", escalated=True, routing_mode="learned",
        actual_cost_usd=3, reference_cost_usd=10, latency_ms=100,
    ))
    db.insert_request(_row(
        id="large", created_at="2026-09-21T11:00:00+00:00", tier_final="large",
        routing_mode="learned", actual_cost_usd=0, reference_cost_usd=0, latency_ms=200, feedback=1,
    ))
    db.insert_request(_row(id="old", created_at="2026-09-18T23:59:59+00:00"))
    db.insert_request(_row(id="future", created_at="2026-09-21T13:00:00+00:00"))

    response = await client.get("/v1/stats", params={"days": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["totals"] == {"requests": 4, "escalations": 1, "escalation_rate": 0.25}
    assert data["cost"] == {"actual_usd": 6, "reference_usd": 20, "saved_usd": 14, "saved_pct": 70}
    assert data["quality"]["feedback_count"] == 3
    assert data["quality"]["positive_rate"] == pytest.approx(2 / 3)
    assert data["quality"]["by_tier"]["small"] == {"count": 2, "positive_rate": 0.5}
    assert data["quality"]["by_tier"]["medium"] == {"count": 0, "positive_rate": None}
    assert data["tier_distribution"] == {"small": 2, "medium": 1, "large": 1}
    assert data["latency"]["small"] == {"p50": 20, "p95": 29}
    assert data["latency"]["medium"] == {"p50": 100, "p95": 100}
    assert data["routing_modes"] == {"heuristic": 1, "learned": 2, "forced": 1}
    assert data["timeline"] == [
        {"date": "2026-09-19", "requests": 0, "saved_usd": 0, "positive_rate": None},
        {"date": "2026-09-20", "requests": 1, "saved_usd": 3, "positive_rate": 1},
        {"date": "2026-09-21", "requests": 3, "saved_usd": 11, "positive_rate": 0.5},
    ]


@pytest.mark.asyncio
async def test_dashboard_boundaries_and_negative_savings(
    client: httpx.AsyncClient, stats_clock: None
) -> None:
    """Include exact time bounds and report overspend rather than clamping savings."""
    db.insert_request(_row(
        id="start", created_at="2026-09-21T00:00:00+00:00", actual_cost_usd=2, reference_cost_usd=1,
    ))
    db.insert_request(_row(
        id="now", created_at="2026-09-21T12:00:00+00:00", actual_cost_usd=2, reference_cost_usd=1,
    ))
    db.insert_request(_row(id="previous-day", created_at="2026-09-20T23:59:59.999999+00:00"))
    db.insert_request(_row(id="later", created_at="2026-09-21T12:00:00.000001+00:00"))

    response = await client.get("/v1/stats", params={"days": 1})

    assert response.status_code == 200
    assert response.json()["totals"]["requests"] == 2
    assert response.json()["cost"] == {
        "actual_usd": 4, "reference_usd": 2, "saved_usd": -2, "saved_pct": -100,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("days", ["0", "-1", "366", "seven", "1.5"])
async def test_dashboard_days_validation(client: httpx.AsyncClient, days: str) -> None:
    """Reject unbounded or invalid dashboard ranges before querying storage."""
    response = await client.get("/v1/stats", params={"days": days})

    assert response.status_code == 422