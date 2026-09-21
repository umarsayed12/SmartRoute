"""Expose paginated request summaries and complete persisted request details."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app import db

router = APIRouter(prefix="/v1", tags=["requests"])


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