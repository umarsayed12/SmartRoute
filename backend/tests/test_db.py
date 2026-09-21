"""Verify SQLite persistence, filters, pagination, and feedback training rows."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import db


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
        "tier": "medium", "escalated": "false", "feedback": "0", "search": "hello",
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
])
async def test_history_query_validation(
    client: httpx.AsyncClient, parameters: dict[str, str]
) -> None:
    """Reject invalid query values before reaching the SQLite helpers."""
    response = await client.get("/v1/requests", params=parameters)

    assert response.status_code == 422