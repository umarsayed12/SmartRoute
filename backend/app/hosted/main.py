"""Assemble authenticated preview and gated public applications without legacy global routes."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.hosted.api import bearer, current_principal, router
from app.hosted.config import HostedSettings, auth_base_url, database_engine, public_origin
from app.hosted.access import validate_runtime_database
from app.hosted.identity import Identity, NeonTokenVerifier
from app.hosted.security import PublicBoundary, WindowLimiter
from app.hosted.store import WorkspaceStore
from app.web import WEB_DIRECTORY, mount_frontend


def create_workspace_app(
    configured: HostedSettings | None = None,
    store: WorkspaceStore | None = None,
    verifier: NeonTokenVerifier | None = None,
    profile_resolver: Callable[[Identity], Identity] | None = None,
    *, public: bool = False, frontend_directory: Path = WEB_DIRECTORY,
) -> FastAPI:
    """Build one scoped application; public mode requires release approval and runtime RLS."""
    configuration = configured or HostedSettings()
    public_auth_url = auth_base_url(configuration)
    origin = public_origin(configuration) if public else None
    mode = "hosted" if public else "preview"

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Create hosted resources without migrations or legacy SQLite initialization."""
        actual_store = store or WorkspaceStore(database_engine(configuration))
        if public:
            try:
                await run_in_threadpool(validate_runtime_database, actual_store.engine)
            except Exception:
                if store is None:
                    actual_store.engine.dispose()
                raise RuntimeError("Public database readiness failed. Verify migrations, runtime role, and tenant policies using the deployment guide.") from None
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            application.state.store = actual_store
            application.state.configuration = configuration
            application.state.verifier = verifier or NeonTokenVerifier(configuration, client)
            application.state.provider_client = client
            application.state.profile_resolver = profile_resolver or actual_store.neon_profile
            application.state.training_lock = Lock()
            application.state.training_workspaces = set()
            application.state.inference_lock = Lock()
            application.state.inference_workspaces = set()
            application.state.public_mode = public
            application.state.workspace_limiter = WindowLimiter(configuration.WORKSPACE_REQUESTS_PER_MINUTE)
            async def retention() -> None:
                """Apply the documented retention policy while this instance is running."""
                while True:
                    try:
                        await run_in_threadpool(actual_store.prune_expired, configuration.REQUEST_RETENTION_DAYS)
                    except Exception:
                        logging.getLogger(__name__).warning("Workspace retention cleanup failed; retry scheduled.")
                    await asyncio.sleep(3600)
            cleanup = asyncio.create_task(retention()) if public else None
            try:
                yield
            finally:
                if cleanup:
                    cleanup.cancel()
                    with suppress(asyncio.CancelledError):
                        await cleanup
                if store is None:
                    actual_store.engine.dispose()

    application = FastAPI(title="SmartRoute", version="0.1.0", lifespan=lifespan,
                          redirect_slashes=not public,
                          docs_url=None if public else "/docs", redoc_url=None if public else "/redoc", openapi_url=None if public else "/openapi.json")

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        """Do not echo invalid credential-bearing request bodies in validation errors."""
        return JSONResponse(status_code=422, content={"detail": "Request contains invalid fields or values."})

    application.add_middleware(
        CORSMiddleware, allow_origins=[origin] if public else ["http://127.0.0.1:5173", "http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
        allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-SmartRoute-Source"],
    )

    @application.middleware("http")
    async def private_preview(request: Request, call_next: Callable) -> Any:
        """Keep preview traffic on loopback and mask database failures without exposing secrets."""
        try:
            local = request.client is not None and ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        if not public and not local:
            return JSONResponse(status_code=403, content={"detail": "Authenticated preview is loopback-only."})
        try:
            response = await call_next(request)
            if request.url.path.startswith("/v1") or request.url.path == "/health":
                response.headers["Cache-Control"] = "no-store"
            return response
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"detail": "Workspace storage is unavailable."})

    @application.get("/v1/client-config")
    def client_config() -> dict[str, Any]:
        """Expose public auth configuration, never database URLs or service secrets."""
        return {"mode": mode, "auth_url": public_auth_url, "inference_enabled": True,
            **({"retention_days": configuration.REQUEST_RETENTION_DAYS} if public else {})}

    @application.get("/health")
    async def health(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict[str, Any]:
        """Return public readiness and owned artifact state only when credentials are supplied."""
        present = False
        if credentials is not None:
            actor = await current_principal(request, credentials)
            report = await run_in_threadpool(request.app.state.store.training_status, actor)
            present = bool(report.get("trained"))
        return {"status": "ok", "mode": mode, "tiers": [], "ollama": False, "model_file_present": present}

    application.include_router(router)
    mount_frontend(application, frontend_directory, required=public)
    if public:
        application.add_middleware(PublicBoundary, configured=configuration, origin=origin)
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname], www_redirect=False)
    return application


def create_preview_app(
    configured: HostedSettings | None = None, store: WorkspaceStore | None = None,
    verifier: NeonTokenVerifier | None = None, profile_resolver: Callable[[Identity], Identity] | None = None,
) -> FastAPI:
    """Preserve the loopback-only preview factory and its test injection contract."""
    return create_workspace_app(configured, store, verifier, profile_resolver)