"""Authenticate every workspace endpoint and separate owner actions from gateway-key use."""

import asyncio
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, time, timedelta, timezone
from io import BytesIO
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import joblib
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.stats import summarize_stats
from app.api.testlab import MAX_OUTPUT_TOKENS, SuiteRunRequest, _summarize, get_suites, load_suite
from app.config import RuntimeSettings
from app.hosted.identity import IdentityServiceUnavailableError, InvalidIdentityError
from app.hosted.store import Principal, WorkspaceStore
from app.hosted.models import CredentialCreate, CredentialReplace, ModelConfiguration, TierName
from app.hosted import providers
from app.hosted.routing import HostedChatRequest, RoutingFailure, route_and_log
from app.routing.features import FEATURE_ORDER
from app.schemas import ChatCompletionResponse, FeedbackRequest, TrainingMetadata
from app.train import fit_router

router = APIRouter(prefix="/v1")
bearer = HTTPBearer(auto_error=False)


def store_for(request: Request) -> WorkspaceStore:
    """Resolve the configured hosted store, never the legacy SQLite module."""
    return request.app.state.store


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    """Resolve JWT or gateway-key identity without accepting tenant IDs from the caller."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    store = store_for(request)
    if token.startswith("sr_"):
        actor = await run_in_threadpool(store.authenticate_api_key, token)
        if actor is None:
            raise HTTPException(status_code=401, detail="Invalid, expired, or revoked API key.", headers={"WWW-Authenticate": "Bearer"})
        return actor
    try:
        identity = await request.app.state.verifier.verify(token)
        identity = await run_in_threadpool(request.app.state.profile_resolver, identity)
        return await run_in_threadpool(store.provision, identity)
    except InvalidIdentityError:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired.", headers={"WWW-Authenticate": "Bearer"}) from None
    except IdentityServiceUnavailableError:
        raise HTTPException(status_code=503, detail="Authentication service is unavailable.") from None
    except PermissionError:
        raise HTTPException(status_code=401, detail="The authenticated account is unavailable.") from None


def owner(actor: Annotated[Principal, Depends(current_principal)]) -> Principal:
    """Restrict administrative mutations to an interactive owner session."""
    if actor.auth_type != "session":
        raise HTTPException(status_code=403, detail="An owner session is required for this operation.")
    return actor


Actor = Annotated[Principal, Depends(current_principal)]
Owner = Annotated[Principal, Depends(owner)]
Store = Annotated[WorkspaceStore, Depends(store_for)]


def verified_owner(actor: Owner) -> Principal:
    """Require verified email before accepting credentials that can incur provider charges."""
    if not actor.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before configuring models.")
    return actor


VerifiedOwner = Annotated[Principal, Depends(verified_owner)]


@router.get("/credentials")
def credentials(actor: Owner, store: Store) -> list[dict[str, Any]]:
    """Return redacted metadata for the owner's stored provider credentials."""
    return store.credentials(actor)


@router.post("/credentials", status_code=201)
def create_credential(body: CredentialCreate, request: Request, actor: VerifiedOwner, store: Store) -> dict[str, Any]:
    """Persist a supported provider key encrypted at rest without echoing it."""
    try:
        return store.create_credential(actor, body, request.app.state.configuration)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="A credential with this provider and label already exists.") from None
    except ValueError:
        raise HTTPException(status_code=400, detail="Credential could not be saved. Check limits and server encryption configuration.") from None


@router.put("/credentials/{credential_id}")
def replace_credential(credential_id: UUID, body: CredentialReplace, request: Request, actor: VerifiedOwner, store: Store) -> dict[str, bool]:
    """Rotate an owned key while preserving references from its models."""
    try:
        if not store.replace_credential(actor, credential_id, body.api_key.get_secret_value(), request.app.state.configuration):
            raise HTTPException(status_code=404, detail="Provider credential not found.")
    except ValueError:
        raise HTTPException(status_code=503, detail="Provider encryption is unavailable.") from None
    return {"updated": True}


@router.delete("/credentials/{credential_id}", status_code=204)
def delete_credential(credential_id: UUID, actor: Owner, store: Store) -> Response:
    """Delete an owned credential and its model mappings, not historical request records."""
    if not store.delete_credential(actor, credential_id):
        raise HTTPException(status_code=404, detail="Provider credential not found.")
    return Response(status_code=204)


@router.get("/models")
def models(actor: Actor, store: Store) -> list[dict[str, Any]]:
    """List the authenticated workspace's configured models without provider secrets."""
    return store.model_rows(actor)


@router.put("/models/{tier}")
def configure_model(tier: TierName, body: ModelConfiguration, actor: VerifiedOwner, store: Store) -> dict[str, Any]:
    """Create or replace one tier using an owned credential and explicit token prices."""
    try:
        return store.configure_model(actor, tier, body)
    except LookupError:
        raise HTTPException(status_code=404, detail="Provider credential not found.") from None


@router.delete("/models/{tier}", status_code=204)
def delete_model(tier: TierName, actor: Owner, store: Store) -> Response:
    """Remove a workspace tier without substituting a shared or local default."""
    if not store.delete_model(actor, tier):
        raise HTTPException(status_code=404, detail="Model tier not found.")
    return Response(status_code=204)


class KeyRequest(BaseModel):
    """Accept only a human label and bounded lifetime for a new gateway key."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(default=90, ge=1, le=365, strict=True)


@router.get("/me")
def me(actor: Actor, store: Store) -> dict[str, Any]:
    """Return the authenticated account's private workspace summary."""
    return store.workspace(actor)


@router.get("/api-keys")
def keys(actor: Owner, store: Store) -> list[dict[str, Any]]:
    """List owner-visible key metadata without hashes or plaintext tokens."""
    return store.list_api_keys(actor)


@router.post("/api-keys", status_code=201)
def create_key(body: KeyRequest, response: Response, actor: Owner, store: Store) -> dict[str, Any]:
    """Issue a gateway credential once, only for an email-verified owner."""
    if not actor.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before creating an API key.")
    response.headers["Cache-Control"] = "no-store"
    try:
        return store.create_api_key(actor, body.name, body.expires_in_days)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: UUID, actor: Owner, store: Store) -> Response:
    """Revoke only a key belonging to the current owner workspace."""
    if not store.revoke_api_key(actor, key_id):
        raise HTTPException(status_code=404, detail="API key not found.")
    return Response(status_code=204)


@router.get("/requests")
def requests(
    actor: Actor, store: Store,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    tier: Literal["small", "medium", "large"] | None = None,
    escalated: bool | None = None,
    feedback: Annotated[int | None, Query(ge=-1, le=1)] = None,
    search: str | None = None,
    source: Literal["api", "playground", "testlab", "sdk"] | None = None,
) -> dict[str, Any]:
    """Read a tenant-filtered request page with the established frontend contract."""
    return store.list_requests(actor, limit, offset, tier=tier, escalated=escalated, feedback=feedback, search=search, source=source)


@router.get("/requests/{request_id}")
def request_detail(request_id: str, actor: Actor, store: Store) -> dict[str, Any]:
    """Return an owned request or the same 404 used for unknown IDs."""
    row = store.get_request(actor, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return row


@router.post("/feedback")
def feedback(body: FeedbackRequest, actor: Actor, store: Store) -> FeedbackRequest:
    """Attach feedback only to the authenticated workspace's request."""
    if not store.set_feedback(actor, body.request_id, body.score, body.note):
        raise HTTPException(status_code=404, detail="Request not found.")
    return body


@router.get("/stats")
def stats(actor: Actor, store: Store, days: Annotated[int, Query(ge=1, le=365)] = 7) -> dict[str, Any]:
    """Aggregate only owned data over the same UTC window as the local prototype."""
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date() - timedelta(days=days - 1), time.min, tzinfo=timezone.utc)
    return summarize_stats(store.stats_rows(actor, start, now), days, now)


@router.get("/settings")
def settings(actor: Actor, store: Store) -> RuntimeSettings:
    """Read the workspace's routing settings."""
    return store.settings(actor)


@router.put("/settings")
def update_settings(body: RuntimeSettings, actor: Owner, store: Store) -> RuntimeSettings:
    """Persist owner edits without changing other workspaces or process globals."""
    try:
        return store.update_settings(actor, body)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/tiers")
async def tiers(request: Request, actor: Actor, store: Store) -> list[dict[str, Any]]:
    """Probe only the workspace's enabled models at fixed provider metadata endpoints."""
    rows = await run_in_threadpool(store.model_rows, actor)
    async def probe(row: dict[str, Any]) -> dict[str, Any]:
        """Keep keys and ciphertext internal even when an availability check fails."""
        available = False
        if row["enabled"]:
            try:
                provider, key = await run_in_threadpool(store.provider_key, actor, row["credential_id"], request.app.state.configuration)
                available = await providers.reachable(request.app.state.provider_client, provider, row["model"], key)
            except (LookupError, ValueError):
                pass
        return {"name": row["tier"], "model": row["model"], "provider": row["provider"], "base_url": providers.ROOTS[row["provider"]],
                "enabled": row["enabled"], "reachable": available, "input_price_per_1k": float(row["input_price_per_1k"]), "output_price_per_1k": float(row["output_price_per_1k"])}
    return await asyncio.gather(*(probe(row) for row in rows))


@router.get("/train/status")
def training_status(actor: Actor, store: Store) -> dict[str, Any]:
    """Read only the authenticated workspace's saved training report."""
    report = store.training_status(actor)
    return TrainingMetadata.model_validate(report).model_dump(mode="json") if report.get("trained") else {"trained": False}


@router.post("/train")
def train(request: Request, actor: Owner, store: Store) -> dict[str, Any]:
    """Fit and save a classifier using only the owner's labelled rows."""
    with request.app.state.training_lock:
        if actor.workspace_id in request.app.state.training_workspaces:
            raise HTTPException(status_code=409, detail="Workspace training is already running.")
        request.app.state.training_workspaces.add(actor.workspace_id)
    try:
        report, model = fit_router(store.training_rows(actor))
        if model is not None:
            buffer = BytesIO()
            joblib.dump(model, buffer)
            store.save_model(actor, buffer.getvalue(), report, FEATURE_ORDER)
        return report
    finally:
        with request.app.state.training_lock:
            request.app.state.training_workspaces.discard(actor.workspace_id)


@router.get("/testlab/suites")
def suites(actor: Actor) -> list[dict[str, object]]:
    """Expose suite definitions only after authentication in preview mode."""
    return get_suites()


@router.get("/testlab/runs")
def runs(actor: Actor, store: Store, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> dict[str, Any]:
    """List only owned Test Lab runs."""
    return store.runs(actor, limit, offset)


@contextmanager
def _inference_slot(request: Request, actor: Principal) -> Iterator[None]:
    """Bound preview concurrency without holding database connections during provider calls."""
    if actor.auth_type == "session" and not actor.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email before using provider models.")
    with request.app.state.inference_lock:
        active = request.app.state.inference_workspaces
        if actor.workspace_id in active:
            raise HTTPException(status_code=429, detail="This workspace already has an active inference operation.")
        if len(active) >= 4:
            raise HTTPException(status_code=503, detail="Gateway inference capacity is busy. Try again later.")
        active.add(actor.workspace_id)
    try:
        yield
    finally:
        with request.app.state.inference_lock:
            active.discard(actor.workspace_id)


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completion(
    body: HostedChatRequest, request: Request, actor: Actor, store: Store,
    source: Annotated[Literal["api", "playground", "testlab", "sdk"], Header(alias="X-SmartRoute-Source")] = "api",
) -> ChatCompletionResponse | JSONResponse:
    """Generate and synchronously audit one response using only this workspace's models."""
    with _inference_slot(request, actor):
        try:
            return await route_and_log(actor, store, request.app.state.configuration, request.app.state.provider_client, body, source)
        except RoutingFailure as error:
            return JSONResponse(status_code=error.status, content={"detail": str(error), "request_id": error.request_id})


@router.post("/testlab/run")
async def run_suite(body: SuiteRunRequest, request: Request, actor: Actor, store: Store) -> dict[str, Any]:
    """Run the shared suite sequentially with workspace-scoped inference and history."""
    with _inference_slot(request, actor):
        run_id = f"testlab-{uuid4().hex}"
        created = datetime.now(timezone.utc)
        results = []
        for prompt in load_suite()[:body.limit]:
            try:
                completion = await route_and_log(actor, store, request.app.state.configuration, request.app.state.provider_client,
                    HostedChatRequest(model=f"smartroute/{body.mode}", messages=[{"role": "user", "content": prompt.prompt}], max_tokens=MAX_OUTPUT_TOKENS), "testlab")
            except RoutingFailure as error:
                raise HTTPException(status_code=error.status, detail=f"Suite stopped at {prompt.id} after {len(results)} completed prompts. {error}") from None
            routing = completion.smartroute
            results.append({"id": prompt.id, "request_id": completion.id, "prompt": prompt.prompt, "expected_tier": prompt.expected_tier,
                "tier_final": routing.tier_final, "escalated": routing.escalated, "confidence": routing.confidence, "latency_ms": routing.latency_ms,
                "actual_cost_usd": routing.actual_cost_usd, "reference_cost_usd": routing.reference_cost_usd, "match": routing.tier_final == prompt.expected_tier})
        values = {"run_id": run_id, "created_at": created, "suite": body.suite, "mode": body.mode, "prompt_count": len(results), "summary": _summarize(results), "results": results}
        await run_in_threadpool(store.record_run, actor, values)
        return values