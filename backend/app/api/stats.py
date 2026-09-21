"""Expose dashboard aggregates, paginated request summaries, and full request details."""

from datetime import datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app import db

router = APIRouter(prefix="/v1", tags=["requests"])


def _quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count rated answers and return their positive fraction, or none when unrated."""
    rated = [row for row in rows if row["feedback"] is not None]
    return {
        "count": len(rated),
        "positive_rate": sum(row["feedback"] == 1 for row in rated) / len(rated) if rated else None,
    }


def _latency(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Compute linearly interpolated routing-time percentiles in milliseconds."""
    if not rows:
        return {"p50": None, "p95": None}
    median, percentile = np.percentile([row["latency_ms"] for row in rows], [50, 95])
    return {"p50": float(median), "p95": float(percentile)}


@router.get("/stats")
def get_stats(days: Annotated[int, Query(ge=1, le=365)] = 7) -> dict[str, Any]:
    """Summarize the last N UTC calendar days, including today up to the current time."""
    now = datetime.now(timezone.utc)
    start_date = now.date() - timedelta(days=days - 1)
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    rows = db.rows_for_stats(start.isoformat(), now.isoformat())
    by_tier: dict[str, list[dict[str, Any]]] = {tier: [] for tier in ("small", "medium", "large")}
    by_day = {start_date + timedelta(days=offset): [] for offset in range(days)}
    modes = {"heuristic": 0, "learned": 0, "forced": 0}
    for row in rows:
        by_tier.setdefault(row["tier_final"], []).append(row)
        day = datetime.fromisoformat(row["created_at"]).astimezone(timezone.utc).date()
        by_day[day].append(row)
        modes[row["routing_mode"]] = modes.get(row["routing_mode"], 0) + 1

    actual = sum(row["actual_cost_usd"] for row in rows)
    reference = sum(row["reference_cost_usd"] for row in rows)
    saved = reference - actual
    escalations = sum(row["escalated"] for row in rows)
    quality = _quality(rows)
    return {
        "totals": {
            "requests": len(rows), "escalations": escalations,
            "escalation_rate": escalations / len(rows) if rows else 0.0,
        },
        "cost": {
            "actual_usd": actual, "reference_usd": reference, "saved_usd": saved,
            "saved_pct": saved / reference * 100 if reference else 0.0,
        },
        "quality": {
            "feedback_count": quality["count"], "positive_rate": quality["positive_rate"],
            "by_tier": {tier: _quality(records) for tier, records in by_tier.items()},
        },
        "tier_distribution": {tier: len(records) for tier, records in by_tier.items()},
        "latency": {tier: _latency(records) for tier, records in by_tier.items()},
        "timeline": [
            {
                "date": day.isoformat(), "requests": len(records),
                "saved_usd": sum(row["reference_cost_usd"] - row["actual_cost_usd"] for row in records),
                "positive_rate": _quality(records)["positive_rate"],
            }
            for day, records in by_day.items()
        ],
        "routing_modes": modes,
    }


@router.get("/requests")
def get_requests(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    tier: Literal["small", "medium", "large"] | None = None,
    escalated: bool | None = None,
    feedback: Annotated[int | None, Query(ge=-1, le=1)] = None,
    search: str | None = None,
) -> dict[str, Any]:
    """List newest request summaries with filters and offset pagination."""
    return db.list_requests(
        limit=limit, offset=offset, tier=tier,
        escalated=escalated, feedback=feedback, search=search,
    )


@router.get("/requests/{request_id}")
def get_request(request_id: str) -> dict[str, Any]:
    """Return the complete stored prompt, answer, and routing record, or 404."""
    row = db.get_request(request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return row