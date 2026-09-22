"""Assemble the isolated loopback-only authenticated preview application."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from ipaddress import ip_address
from threading import Lock
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.hosted.api import bearer, current_principal, router
from app.hosted.config import HostedSettings, auth_base_url, database_engine
from app.hosted.identity import Identity, NeonTokenVerifier
from app.hosted.store import WorkspaceStore


def create_preview_app(
    configured: HostedSettings | None = None,
    store: WorkspaceStore | None = None,
    verifier: NeonTokenVerifier | None = None,
    profile_resolver: Callable[[Identity], Identity] | None = None,
) -> FastAPI:
    """Build a private preview with injectable infrastructure for isolated tests."""
    configuration = configured or HostedSettings()
    public_auth_url = auth_base_url(configuration)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Create hosted resources without migrations or legacy SQLite initialization."""
        actual_store = store or WorkspaceStore(database_engine(configuration))
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            application.state.store = actual_store
            application.state.verifier = verifier or NeonTokenVerifier(configuration, client)
            application.state.profile_resolver = profile_resolver or actual_store.neon_profile
            application.state.training_lock = Lock()
            application.state.training_workspaces = set()
            try:
                yield
            finally:
                if store is None:
                    actual_store.engine.dispose()

    application = FastAPI(title="SmartRoute authenticated preview", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
        allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-SmartRoute-Source"],
    )

    @application.middleware("http")
    async def private_preview(request: Request, call_next: Callable) -> Any:
        """Keep preview traffic on loopback and mask database failures without exposing secrets."""
        try:
            local = request.client is not None and ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not local:
            return JSONResponse(status_code=403, content={"detail": "Authenticated preview is loopback-only."})
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"detail": "Workspace storage is unavailable."})

    @application.get("/v1/client-config")
    def client_config() -> dict[str, Any]:
        """Expose public auth configuration, never database URLs or service secrets."""
        return {"mode": "preview", "auth_url": public_auth_url, "inference_enabled": False}

    @application.get("/health")
    async def health(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict[str, Any]:
        """Return public readiness and owned artifact state only when credentials are supplied."""
        present = False
        if credentials is not None:
            actor = await current_principal(request, credentials)
            report = await run_in_threadpool(request.app.state.store.training_status, actor)
            present = bool(report.get("trained"))
        return {"status": "ok", "mode": "preview", "tiers": [], "ollama": False, "model_file_present": present}

    application.include_router(router)
    return application