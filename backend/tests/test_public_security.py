"""Test public configuration gates, bounded requests, and rate limits without external services."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from sqlalchemy import insert, update

from app.hosted import main as hosted_main, schema
from app.hosted.access import validate_runtime_database
from app.hosted.config import HostedSettings, public_origin
from app.hosted.identity import Identity, InvalidIdentityError
from app.hosted.security import PublicBoundary, WindowLimiter
from app.hosted.store import WorkspaceStore


def configuration(**overrides: object) -> HostedSettings:
    """Construct only synthetic public settings, never reading local environment files."""
    values = dict(HOSTED_RELEASE_APPROVED=True, PUBLIC_BASE_URL="https://gateway.example.test",
                  NEON_AUTH_BASE_URL="https://auth.example.test/db/auth", NEON_AUTH_ISSUER="https://auth.example.test",
                  NEON_AUTH_AUDIENCE="https://auth.example.test", PROVIDER_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"))
    return HostedSettings(_env_file=None, **{**values, **overrides})


@pytest.mark.parametrize("overrides", [{"HOSTED_RELEASE_APPROVED": False}, {"PUBLIC_BASE_URL": "http://gateway.example.test"},
    {"PUBLIC_BASE_URL": "https://gateway.example.test/path"}, {"NEON_AUTH_ISSUER": ""}, {"PROVIDER_ENCRYPTION_KEY": "bad"},
    {"DATABASE_DIRECT_URL": "owner-url-must-not-be-deployed"}])
def test_public_configuration_fails_closed(overrides: dict[str, object]) -> None:
    """Approval cannot substitute for origin, identity, encryption, and runtime-role separation."""
    with pytest.raises(ValueError):
        public_origin(configuration(**overrides))


def test_limiter_bounds_and_expiry() -> None:
    """Limit individual identities, cap memory, and recover on a new minute window."""
    limiter = WindowLimiter(2, capacity=1)
    assert limiter.allow("one", 0) and limiter.allow("one", 1)
    assert not limiter.allow("one", 2) and not limiter.allow("two", 2)
    assert limiter.allow("two", 60)


@pytest.mark.asyncio
async def test_public_http_boundary() -> None:
    """Reject cross-origin, excessive, encoded, and oversized traffic without echoing inputs."""
    settings = configuration(REQUEST_MAX_BYTES=4096, GLOBAL_REQUESTS_PER_MINUTE=10)
    app = FastAPI()
    @app.post("/v1/echo")
    async def echo(request: Request) -> dict[str, int]:
        """Confirm a valid buffered request still reaches ordinary route parsing."""
        return {"length": len(await request.body())}
    app.add_middleware(PublicBoundary, configured=settings, origin=public_origin(settings))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=settings.PUBLIC_BASE_URL) as client:
        assert (await client.post("/v1/echo", headers={"Origin": "https://other.example.test"})).status_code == 403
        assert (await client.post("/v1/echo", content="x" * 4097)).status_code == 413
        assert (await client.post("/v1/echo", content="secret", headers={"Content-Encoding": "gzip"})).status_code == 415
        response = await client.post("/v1/echo", content="hello")
        assert response.json() == {"length": 5}
        assert response.headers["cache-control"] == "no-store" and response.headers["x-frame-options"] == "DENY"
        assert "https://auth.example.test" in response.headers["content-security-policy"]
        assert "font-src 'self' data:" in response.headers["content-security-policy"]
        for _index in range(10):
            response = await client.post("/v1/echo")
        assert response.status_code == 429 and response.headers["retry-after"] == "60"


@pytest.mark.asyncio
async def test_chunked_body_and_deadline() -> None:
    """A missing content-length cannot bypass size limits and stalled work gets a deadline."""
    settings = configuration(REQUEST_MAX_BYTES=4096)
    app = FastAPI()
    @app.post("/v1/stall")
    async def stall() -> None:
        """Wait until the boundary cancels this deterministic test request."""
        await asyncio.Event().wait()
    async def chunks():
        """Stream an oversized body without a declared content length."""
        yield b"x" * 3000
        yield b"x" * 3000
    app.add_middleware(PublicBoundary, configured=settings, origin=public_origin(settings))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=settings.PUBLIC_BASE_URL) as client:
        assert (await client.post("/v1/stall", content=chunks())).status_code == 413
        settings.REQUEST_TIMEOUT_SECONDS = 0.01
        response = await client.post("/v1/stall")
        assert response.status_code == 504 and "Check history" in response.json()["detail"]


@pytest.mark.asyncio
async def test_public_app_with_built_frontend(store: WorkspaceStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosted HTTP traffic keeps authentication and host checks while serving direct page refreshes."""
    (tmp_path / "index.html").write_text("<html>Built SmartRoute</html>", encoding="utf-8")
    monkeypatch.setattr(hosted_main, "validate_runtime_database", Mock())
    monkeypatch.setattr(store, "prune_expired", Mock())
    verifier = Mock()
    verifier.verify = AsyncMock(return_value=Identity("https://auth.example.test", "owner", "owner@example.test", "Owner", True))
    settings = configuration(WORKSPACE_REQUESTS_PER_MINUTE=1)
    app = hosted_main.create_workspace_app(settings, store, verifier, lambda identity: identity, public=True, frontend_directory=tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("203.0.113.8", 443)), base_url=settings.PUBLIC_BASE_URL) as client:
            assert (await client.get("/integration")).status_code == 200
            assert (await client.get("/v1/client-config")).json()["mode"] == "hosted"
            assert (await client.get("/v1/client-config")).json()["retention_days"] == 30
            assert (await client.get("/health")).json()["status"] == "ok"
            assert (await client.get("/v1/me")).status_code == 401
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/v1/missing")).status_code == 404
            assert (await client.get("/", headers={"Host": "untrusted.example.test"})).status_code == 400
            headers = {"Authorization": "Bearer synthetic.session.jwt"}
            assert (await client.get("/v1/me", headers=headers)).status_code == 200
            assert (await client.get("/v1/me", headers=headers)).status_code == 429
            verifier.verify.side_effect = InvalidIdentityError("private detail")
            assert (await client.get("/v1/me", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_public_database_gate_cannot_be_skipped(store: WorkspaceStore, tmp_path: Path) -> None:
    """Release approval alone cannot make an unverified database public."""
    (tmp_path / "index.html").write_text("<html>Built app</html>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        validate_runtime_database(store.engine)
    app = hosted_main.create_workspace_app(configuration(), store, public=True, frontend_directory=tmp_path)
    with pytest.raises(RuntimeError, match="database readiness"):
        async with app.router.lifespan_context(app):
            pass


def test_daily_capacity_and_retention(store: WorkspaceStore) -> None:
    """Retain current records, limit new inference, and delete expired attempts through their parent."""
    actor = store.provision(Identity("https://auth.example.test", "owner", "owner@example.test", "Owner", True))
    now = datetime.now(timezone.utc)
    row = dict(id="record-test", created_at=now, prompt_preview="Synthetic", messages=[], answer="Answer", features={},
               tier_chosen="small", tier_final="small", provider="openai", model="test", escalated=False, confidence=1,
               reason="test", routing_mode="forced", prompt_tokens=1, completion_tokens=1, latency_ms=1,
               actual_cost_usd=0, reference_cost_usd=0, source="sdk")
    store.record_inference(actor, row, [dict(kind="answer", status="completed", tier="small", provider="openai", model="test",
                                          prompt_tokens=1, completion_tokens=1, latency_ms=1, cost_usd=0, usage_details={})])
    assert "daily" in store.inference_capacity(actor, configuration(WORKSPACE_INFERENCES_PER_DAY=1))
    store.prune_expired(30)
    assert store.list_requests(actor)["total"] == 1
    with store.engine.begin() as connection:
        connection.execute(update(schema.requests).values(created_at=now - timedelta(days=31)))
    store.prune_expired(30)
    assert store.list_requests(actor)["total"] == 0 and store.inference_capacity(actor, configuration()) is None