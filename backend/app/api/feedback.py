"""Store user ratings that supply labels for the learned routing policy."""

from fastapi import APIRouter, HTTPException

from app import db
from app.schemas import FeedbackRequest

router = APIRouter(prefix="/v1", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackRequest)
def submit_feedback(request: FeedbackRequest) -> FeedbackRequest:
    """Save or replace a rating, returning 404 when its request has not been logged."""
    if not db.set_feedback(request.request_id, request.score, request.note):
        raise HTTPException(status_code=404, detail="Request not found.")
    return request