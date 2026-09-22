"""Run a fixed prompt suite through normal chat routing and retain run summaries."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app import db
from app.api.chat import create_chat_completion
from app.schemas import ChatCompletionRequest, ChatMessage

router = APIRouter(prefix="/v1/testlab", tags=["testlab"])
SUITE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "prompts.jsonl"
MAX_OUTPUT_TOKENS = 256
_run_lock = Lock()


class SuitePrompt(BaseModel):
    """Describe one prompt and its expected routing tier."""

    id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    expected_tier: Literal["small", "medium", "large"]
    category: str = Field(min_length=1)


class SuiteRunRequest(BaseModel):
    """Choose the built-in suite, routing mode, and optional prefix length."""

    suite: Literal["default"] = "default"
    mode: Literal["auto", "small", "medium", "large"] = "auto"
    limit: int | None = Field(default=None, ge=1, le=40, strict=True)


def load_suite() -> list[SuitePrompt]:
    """Read JSONL records and reject an unreadable, empty, or ambiguous suite."""
    try:
        prompts = [
            SuitePrompt.model_validate_json(line)
            for line in SUITE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not prompts or len({prompt.id for prompt in prompts}) != len(prompts):
            raise ValueError("The suite is empty or contains duplicate IDs.")
        return prompts
    except (OSError, UnicodeError, ValidationError, ValueError) as error:
        raise HTTPException(status_code=500, detail="The prompt suite is unavailable or invalid.") from error


@router.get("/suites")
def get_suites() -> list[dict[str, object]]:
    """List the built-in suite and its expected-tier distribution."""
    prompts = load_suite()
    return [{
        "id": "default", "name": "Default", "count": len(prompts),
        "tier_distribution": dict(Counter(prompt.expected_tier for prompt in prompts)),
        "max_tokens": MAX_OUTPUT_TOKENS,
    }]


def _summarize(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute raw final-tier match accuracy and aggregate measured cost and latency."""
    count = len(results)
    actual = sum(result["actual_cost_usd"] for result in results)
    reference = sum(result["reference_cost_usd"] for result in results)
    return {
        "routing_accuracy": sum(result["match"] for result in results) / count if count else 0.0,
        "escalation_rate": sum(result["escalated"] for result in results) / count if count else 0.0,
        "avg_latency_ms": sum(result["latency_ms"] for result in results) / count if count else 0.0,
        "total_actual_usd": actual,
        "total_reference_usd": reference,
        "saved_pct": (reference - actual) / reference * 100 if reference else 0.0,
    }


@router.post("/run")
async def run_suite(request: SuiteRunRequest) -> dict[str, Any]:
    """Run prompts sequentially through chat, flushing each request log before the next."""
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A Test Lab run is already in progress.")
    try:
        prompts = load_suite()[:request.limit]
        run_id = f"testlab-{uuid4().hex}"
        created_at = datetime.now(timezone.utc).isoformat()
        results: list[dict[str, Any]] = []
        for prompt in prompts:
            background_tasks = BackgroundTasks()
            try:
                completion = await create_chat_completion(
                    ChatCompletionRequest(
                        model=f"smartroute/{request.mode}",
                        messages=[ChatMessage(role="user", content=prompt.prompt)],
                        max_tokens=MAX_OUTPUT_TOKENS,
                    ),
                    background_tasks=background_tasks,
                    source="testlab",
                )
                await background_tasks()
            except HTTPException as error:
                raise HTTPException(
                    status_code=error.status_code,
                    detail=f"Suite stopped at {prompt.id} after {len(results)} completed prompts. {error.detail}",
                ) from error
            routing = completion.smartroute
            results.append({
                "id": prompt.id,
                "request_id": routing.request_id,
                "prompt": prompt.prompt,
                "expected_tier": prompt.expected_tier,
                "tier_final": routing.tier_final,
                "escalated": routing.escalated,
                "confidence": routing.confidence,
                "latency_ms": routing.latency_ms,
                "actual_cost_usd": routing.actual_cost_usd,
                "reference_cost_usd": routing.reference_cost_usd,
                "match": routing.tier_final == prompt.expected_tier,
            })
        summary = _summarize(results)
        run = {
            "run_id": run_id, "created_at": created_at,
            "suite": request.suite, "mode": request.mode,
            "prompt_count": len(results), "summary": summary,
        }
        await run_in_threadpool(db.insert_testlab_run, run)
        return {**run, "results": results}
    finally:
        _run_lock.release()


@router.get("/runs")
def get_runs(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """List saved summaries for completed Test Lab runs."""
    return db.list_testlab_runs(limit=limit, offset=offset)