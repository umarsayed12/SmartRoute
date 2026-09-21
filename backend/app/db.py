"""Persist request details in SQLite and provide filtered reads and feedback helpers."""

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from app.config import settings

_SUMMARY_COLUMNS = """
    id, created_at, prompt_preview, tier_chosen, tier_final, escalated,
    confidence, reason, routing_mode, prompt_tokens, completion_tokens,
    latency_ms, actual_cost_usd, reference_cost_usd, feedback, feedback_note, source
"""


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Commit or roll back an operation, then always close its connection."""
    connection = sqlite3.connect(settings.DB_PATH, timeout=10.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _request_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert the stored escalation flag to a JSON boolean."""
    record = dict(row)
    record["escalated"] = bool(record["escalated"])
    return record


def init_db() -> None:
    """Create the data directory and request table, preserving existing rows."""
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                prompt_preview TEXT NOT NULL,
                prompt_full TEXT NOT NULL,
                answer_full TEXT NOT NULL,
                features_json TEXT NOT NULL,
                tier_chosen TEXT NOT NULL,
                tier_final TEXT NOT NULL,
                escalated INTEGER NOT NULL CHECK (escalated IN (0, 1)),
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                routing_mode TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                actual_cost_usd REAL NOT NULL,
                reference_cost_usd REAL NOT NULL,
                feedback INTEGER CHECK (feedback IN (-1, 1)),
                feedback_note TEXT,
                source TEXT NOT NULL CHECK (source IN ('api', 'playground', 'testlab', 'sdk'))
            );
            CREATE INDEX IF NOT EXISTS idx_requests_created_at
                ON requests (created_at DESC, id DESC);
        """)


def insert_request(row: Mapping[str, Any]) -> None:
    """Insert one completed request using bound parameters and optional feedback defaults."""
    values = {"feedback": None, "feedback_note": None, "source": "api", **row}
    with _connection() as connection:
        connection.execute("""
            INSERT INTO requests (
                id, created_at, prompt_preview, prompt_full, answer_full, features_json,
                tier_chosen, tier_final, escalated, confidence, reason, routing_mode,
                prompt_tokens, completion_tokens, latency_ms, actual_cost_usd,
                reference_cost_usd, feedback, feedback_note, source
            ) VALUES (
                :id, :created_at, :prompt_preview, :prompt_full, :answer_full, :features_json,
                :tier_chosen, :tier_final, :escalated, :confidence, :reason, :routing_mode,
                :prompt_tokens, :completion_tokens, :latency_ms, :actual_cost_usd,
                :reference_cost_usd, :feedback, :feedback_note, :source
            )
        """, values)


def set_feedback(request_id: str, score: int, note: str | None = None) -> bool:
    """Set a positive or negative rating, returning false when the request is missing."""
    if score not in (-1, 1):
        raise ValueError("Feedback score must be -1 or 1.")
    with _connection() as connection:
        cursor = connection.execute(
            "UPDATE requests SET feedback = ?, feedback_note = ? WHERE id = ?",
            (score, note, request_id),
        )
        return cursor.rowcount > 0


def get_request(request_id: str) -> dict[str, Any] | None:
    """Return a full request record, or none when its ID is unknown."""
    with _connection() as connection:
        row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    return _request_dict(row) if row is not None else None


def list_requests(
    limit: int = 50,
    offset: int = 0,
    tier: str | None = None,
    escalated: bool | None = None,
    feedback: int | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Return a newest-first summary page; tier means final tier and feedback 0 means unrated."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Limit must be 1-100 and offset must be non-negative.")
    if tier not in (None, "small", "medium", "large"):
        raise ValueError("Unknown tier filter.")
    if feedback not in (None, -1, 0, 1):
        raise ValueError("Feedback filter must be -1, 0, or 1.")

    conditions: list[str] = []
    parameters: list[Any] = []
    if tier is not None:
        conditions.append("tier_final = ?")
        parameters.append(tier)
    if escalated is not None:
        conditions.append("escalated = ?")
        parameters.append(int(escalated))
    if feedback == 0:
        conditions.append("feedback IS NULL")
    elif feedback is not None:
        conditions.append("feedback = ?")
        parameters.append(feedback)
    if search:
        conditions.append(
            "(instr(lower(prompt_full), lower(?)) > 0 OR instr(lower(answer_full), lower(?)) > 0)"
        )
        parameters.extend([search, search])
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with _connection() as connection:
        connection.execute("BEGIN")
        total = connection.execute(
            f"SELECT COUNT(*) FROM requests {where}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT {_SUMMARY_COLUMNS} FROM requests {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
    return {
        "items": [_request_dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def rows_for_training() -> list[dict[str, Any]]:
    """Return full records with feedback in a stable order for later router training."""
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM requests WHERE feedback IN (-1, 1) ORDER BY created_at, id"
        ).fetchall()
    return [_request_dict(row) for row in rows]


def rows_for_stats(start_at: str, end_at: str) -> list[dict[str, Any]]:
    """Read only dashboard fields within inclusive UTC ISO timestamp bounds."""
    with _connection() as connection:
        rows = connection.execute(
            "SELECT created_at, tier_final, escalated, feedback, routing_mode, latency_ms, "
            "actual_cost_usd, reference_cost_usd FROM requests "
            "WHERE created_at >= ? AND created_at <= ? ORDER BY created_at",
            (start_at, end_at),
        ).fetchall()
    return [_request_dict(row) for row in rows]