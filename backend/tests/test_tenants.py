"""Prove workspace isolation and gateway-key lifecycle using an isolated SQL database."""

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, Mock
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.pool import StaticPool

from app.config import RuntimeSettings
from app.hosted import schema
from app.hosted.identity import Identity
from app.hosted.identity import InvalidIdentityError, NeonTokenVerifier
from app.hosted.config import HostedSettings
from app.hosted.main import create_preview_app
from app.hosted.store import Principal, WorkspaceStore


@pytest.fixture
def store() -> Iterator[WorkspaceStore]:
    """Create the hosted schema in a shared in-memory SQLite connection for tests only."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}, execution_options={"schema_translate_map": {schema.SCHEMA: None}})
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        schema.metadata.create_all(connection)
    yield WorkspaceStore(engine)
    engine.dispose()


def _identity(subject: str, verified: bool = True) -> Identity:
    """Build a preverified synthetic identity; cryptographic validation is tested separately."""
    return Identity("https://auth.example.test", subject, f"{subject}@example.test", subject, verified)


def _insert_request(store: WorkspaceStore, actor: Principal, request_id: str) -> None:
    """Insert a synthetic owned row to test scoped reads and updates."""
    with store.engine.begin() as connection:
        connection.execute(insert(schema.requests).values(
            id=request_id, workspace_id=actor.workspace_id, prompt_preview="Hello",
            messages=[{"role": "user", "content": "Hello"}], answer="Hello!", features={"prompt_words": 1},
            tier_chosen="small", tier_final="small", provider="openai", model="test-model",
            escalated=False, confidence=0.9, reason="Test", routing_mode="heuristic",
            prompt_tokens=10, completion_tokens=2, latency_ms=10, actual_cost_usd=0,
            reference_cost_usd=0.001, source="sdk",
        ))


def test_idempotent_private_workspaces(store: WorkspaceStore) -> None:
    """Issuer/subject identity is stable and two people never share a workspace."""
    first = store.provision(_identity("first"))
    same = store.provision(_identity("first"))
    second = store.provision(_identity("second"))
    assert first.workspace_id == same.workspace_id
    assert first.workspace_id != second.workspace_id
    assert store.workspace(first)["user"]["email"] == "first@example.test"


def test_request_feedback_and_training_isolation(store: WorkspaceStore) -> None:
    """Cross-workspace IDs cannot reveal or label another tenant's request."""
    first, second = [store.provision(_identity(name)) for name in ("first", "second")]
    _insert_request(store, first, "private-first")
    _insert_request(store, second, "private-second")
    assert store.list_requests(first)["total"] == store.list_requests(second)["total"] == 1
    assert store.get_request(second, "private-first") is None
    assert not store.set_feedback(second, "private-first", -1, "cross-tenant")
    assert store.set_feedback(first, "private-first", 1, "own rating")
    assert len(store.training_rows(first)) == 1
    assert store.training_rows(second) == []
    assert store.get_request(first, "private-first")["feedback"] == 1


def test_settings_are_not_global(store: WorkspaceStore) -> None:
    """Editing one workspace cannot mutate another workspace's routing configuration."""
    first, second = [store.provision(_identity(name)) for name in ("first", "second")]
    store.update_settings(first, RuntimeSettings(confidence_threshold=0.8))
    assert store.settings(first).confidence_threshold == 0.8
    assert store.settings(second).confidence_threshold == 0.6


def test_search_covers_full_prompt_without_crossing_tenants(store: WorkspaceStore) -> None:
    """Search beyond the truncated preview and keep wildcard characters literal."""
    first, second = [store.provision(_identity(name)) for name in ("first", "second")]
    _insert_request(store, first, "private-first")
    with store.engine.begin() as connection:
        connection.execute(update(schema.requests).where(schema.requests.c.id == "private-first").values(
            messages=[{"role": "user", "content": "A full prompt with literal 100%_marker"}],
        ))
    assert store.list_requests(first, search="100%_marker")["total"] == 1
    assert store.list_requests(second, search="100%_marker")["total"] == 0


def test_api_key_scope_revocation_and_expiry(store: WorkspaceStore) -> None:
    """Keys resolve to stored ownership and lose access immediately when revoked or expired."""
    first, second = [store.provision(_identity(name)) for name in ("first", "second")]
    created = store.create_api_key(first, "Application", 30)
    token = created.pop("key")
    actor = store.authenticate_api_key(token)
    assert actor is not None and actor.workspace_id == first.workspace_id
    assert actor.auth_type == "api_key"
    assert store.workspace(actor)["user"] is None
    listed = store.list_api_keys(first)
    assert "key" not in listed[0] and "key_hash" not in listed[0]
    assert store.list_api_keys(second) == []
    with pytest.raises(PermissionError):
        store.create_api_key(actor, "Forbidden", 30)
    with pytest.raises(PermissionError):
        store.update_settings(actor, RuntimeSettings(max_escalations=0))
    assert not store.revoke_api_key(second, actor.api_key_id)
    assert store.revoke_api_key(first, actor.api_key_id)
    assert store.authenticate_api_key(token) is None
    expiring = store.create_api_key(first, "Expired", 1)
    with store.engine.begin() as connection:
        connection.execute(update(schema.api_keys).where(schema.api_keys.c.workspace_id == first.workspace_id).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    assert store.authenticate_api_key(expiring["key"]) is None
    assert store.authenticate_api_key("bad-key") is None


def test_unverified_identity_cannot_create_keys(store: WorkspaceStore) -> None:
    """Require email verification before issuing a durable SDK credential."""
    actor = store.provision(_identity("unverified", False))
    with pytest.raises(PermissionError):
        store.create_api_key(actor, "Application", 30)


def test_stats_runs_and_model_isolation(store: WorkspaceStore) -> None:
    """Every dashboard, run-history, and trained-artifact lookup is tenant scoped."""
    first, second = [store.provision(_identity(name)) for name in ("first", "second")]
    _insert_request(store, first, "private-first")
    now = datetime.now(timezone.utc)
    assert len(store.stats_rows(first, now - timedelta(days=1), now + timedelta(days=1))) == 1
    assert store.stats_rows(second, now - timedelta(days=1), now + timedelta(days=1)) == []
    with store.engine.begin() as connection:
        connection.execute(insert(schema.testlab_runs).values(
            run_id="run-one", workspace_id=first.workspace_id, suite="default", mode="auto",
            prompt_count=1, summary={"routing_accuracy": 1.0}, results=[],
        ))
    assert store.runs(first)["total"] == 1 and store.runs(second)["total"] == 0
    store.save_model(first, b"trusted-test-artifact", {"trained": True, "n_rows": 30}, ["prompt_words"])
    assert store.training_status(first)["trained"] is True
    assert store.training_status(second) == {"trained": False}
    with store.engine.connect() as connection:
        assert len(connection.execute(select(schema.router_models)).all()) == 1


@pytest_asyncio.fixture
async def preview_client(store: WorkspaceStore) -> AsyncIterator[httpx.AsyncClient]:
    """Exercise the real authorization boundary with isolated identity and database infrastructure."""
    async def verify(token: str) -> Identity:
        """Resolve only explicit test sessions; cryptographic validation has separate tests."""
        if token not in ("browser-first", "browser-second", "browser-unverified"):
            raise InvalidIdentityError("Invalid test session.")
        return _identity(token.removeprefix("browser-"), token != "browser-unverified")

    verifier = Mock(spec=NeonTokenVerifier)
    verifier.verify = AsyncMock(side_effect=verify)
    application = create_preview_app(
        HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"),
        store=store, verifier=verifier, profile_resolver=lambda identity: identity,
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application, client=("127.0.0.1", 1234)), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/v1/me"), ("GET", "/v1/api-keys"), ("POST", "/v1/api-keys"),
    ("GET", "/v1/requests"), ("GET", "/v1/requests/private-first"),
    ("POST", "/v1/feedback"), ("GET", "/v1/stats"), ("GET", "/v1/settings"),
    ("PUT", "/v1/settings"), ("GET", "/v1/tiers"), ("POST", "/v1/train"),
    ("GET", "/v1/train/status"), ("GET", "/v1/testlab/suites"),
    ("GET", "/v1/testlab/runs"), ("POST", "/v1/testlab/run"), ("POST", "/v1/chat/completions"),
])
async def test_preview_requires_authentication(preview_client: httpx.AsyncClient, method: str, path: str) -> None:
    """No workspace endpoint exposes the old unauthenticated global data path."""
    response = await preview_client.request(method, path, json={})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_preview_cross_tenant_http_access(preview_client: httpx.AsyncClient, store: WorkspaceStore) -> None:
    """Changing request IDs or sending workspace parameters cannot cross an authenticated tenant boundary."""
    first = store.provision(_identity("first"))
    _insert_request(store, first, "private-first")
    headers = {"Authorization": "Bearer browser-second"}
    detail = await preview_client.get("/v1/requests/private-first", headers=headers)
    rating = await preview_client.post("/v1/feedback", headers=headers, json={"request_id": "private-first", "score": -1})
    page = await preview_client.get("/v1/requests", headers=headers, params={"workspace_id": str(first.workspace_id)})
    stats = await preview_client.get("/v1/stats", headers=headers)
    training = await preview_client.post("/v1/train", headers=headers)
    assert detail.status_code == rating.status_code == 404
    assert page.json()["total"] == stats.json()["totals"]["requests"] == 0
    assert training.json()["trained"] is False and training.json()["n_rows"] == 0
    assert store.get_request(first, "private-first")["feedback"] is None


@pytest.mark.asyncio
async def test_preview_key_permissions_and_revocation(preview_client: httpx.AsyncClient) -> None:
    """Return a key once, reject its owner-only actions, and enforce revocation immediately."""
    owner_headers = {"Authorization": "Bearer browser-first"}
    created = await preview_client.post("/v1/api-keys", headers=owner_headers, json={"name": "SDK test", "expires_in_days": 30})
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    token = created.json()["key"]
    key_id = created.json()["id"]
    key_headers = {"Authorization": f"Bearer {token}"}
    workspace = await preview_client.get("/v1/me", headers=key_headers)
    assert workspace.status_code == 200 and workspace.json()["user"] is None
    for method, path, payload in [("POST", "/v1/api-keys", {"name": "Forbidden"}), ("PUT", "/v1/settings", {}), ("POST", "/v1/train", {})]:
        response = await preview_client.request(method, path, headers=key_headers, json=payload)
        assert response.status_code == 403
    foreign = await preview_client.delete(f"/v1/api-keys/{key_id}", headers={"Authorization": "Bearer browser-second"})
    assert foreign.status_code == 404
    listed = await preview_client.get("/v1/api-keys", headers=owner_headers)
    assert token not in listed.text and "key_hash" not in listed.text
    revoked = await preview_client.delete(f"/v1/api-keys/{key_id}", headers=owner_headers)
    assert revoked.status_code == 204
    denied = await preview_client.get("/v1/stats", headers=key_headers)
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_unverified_and_invalid_sessions(preview_client: httpx.AsyncClient) -> None:
    """Unknown sessions cannot access data, and unverified owners cannot mint durable keys."""
    invalid = await preview_client.get("/v1/me", headers={"Authorization": "Bearer unknown"})
    unverified = await preview_client.post("/v1/api-keys", headers={"Authorization": "Bearer browser-unverified"}, json={"name": "Blocked"})
    assert invalid.status_code == 401
    assert unverified.status_code == 403


@pytest.mark.asyncio
async def test_preview_has_no_local_inference_fallback(preview_client: httpx.AsyncClient) -> None:
    """Authenticated preview never calls shared local providers while M3 is incomplete."""
    headers = {"Authorization": "Bearer browser-first"}
    for path in ("/v1/chat/completions", "/v1/testlab/run"):
        response = await preview_client.post(path, headers=headers, json={})
        assert response.status_code == 409 and "M3" in response.json()["detail"]
    tiers = await preview_client.get("/v1/tiers", headers=headers)
    assert tiers.json() == []
    config = await preview_client.get("/v1/client-config")
    assert config.json()["mode"] == "preview" and config.json()["inference_enabled"] is False


@pytest.mark.asyncio
async def test_preview_rejects_non_loopback_clients(store: WorkspaceStore) -> None:
    """Do not make the migration preview a public service by changing Uvicorn's bind address."""
    application = create_preview_app(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), store=store)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application, client=("192.0.2.10", 1234)), base_url="http://test") as client:
            response = await client.get("/v1/client-config", headers={"X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 403