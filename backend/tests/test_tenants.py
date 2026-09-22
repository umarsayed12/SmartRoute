"""Prove workspace isolation and gateway-key lifecycle using an isolated SQL database."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import httpx
from cryptography.fernet import Fernet
from unittest.mock import AsyncMock, Mock
from sqlalchemy import insert, select, update

from app.config import RuntimeSettings
from app.hosted import providers, schema
from app.hosted.identity import Identity
from app.hosted.identity import InvalidIdentityError, NeonTokenVerifier
from app.hosted.config import HostedSettings
from app.hosted.main import create_preview_app
from app.hosted.store import Principal, WorkspaceStore


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
        if token == "synthetic.owner.jwt":
            return _identity("first")
        if token not in ("browser-first", "browser-second", "browser-unverified"):
            raise InvalidIdentityError("Invalid test session.")
        return _identity(token.removeprefix("browser-"), token != "browser-unverified")

    verifier = Mock(spec=NeonTokenVerifier)
    verifier.verify = AsyncMock(side_effect=verify)
    application = create_preview_app(
        HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth", PROVIDER_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")),
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
    """Authenticated preview never calls shared local providers when owned models are absent."""
    headers = {"Authorization": "Bearer browser-first"}
    for path, body in (("/v1/chat/completions", {"model": "smartroute/auto", "messages": [{"role": "user", "content": "Hi"}]}), ("/v1/testlab/run", {"limit": 1})):
        response = await preview_client.post(path, headers=headers, json=body)
        assert response.status_code == 409 and "workspace model" in response.json()["detail"]
    tiers = await preview_client.get("/v1/tiers", headers=headers)
    assert tiers.json() == []
    config = await preview_client.get("/v1/client-config")
    assert config.json()["mode"] == "preview" and config.json()["inference_enabled"] is True


@pytest.mark.asyncio
async def test_preview_rejects_non_loopback_clients(store: WorkspaceStore) -> None:
    """Do not make the migration preview a public service by changing Uvicorn's bind address."""
    application = create_preview_app(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), store=store)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application, client=("192.0.2.10", 1234)), base_url="http://test") as client:
            response = await client.get("/v1/client-config", headers={"X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owned_model_configuration_and_key_rotation(preview_client: httpx.AsyncClient, store: WorkspaceStore) -> None:
    """Store encrypted credentials, enforce model ownership, and never expose secret fields."""
    first = {"Authorization": "Bearer browser-first"}
    second = {"Authorization": "Bearer browser-second"}
    created = await preview_client.post("/v1/credentials", headers=first, json={
        "provider": "openai", "label": "Primary", "api_key": "synthetic-provider-key",
    })
    assert created.status_code == 201
    credential_id = created.json()["id"]
    assert "synthetic-provider-key" not in created.text
    model = {"credential_id": credential_id, "model": "test-model", "input_price_per_1k": "0.001", "output_price_per_1k": "0.002"}
    denied = await preview_client.put("/v1/models/small", headers=second, json=model)
    assert denied.status_code == 404
    configured = await preview_client.put("/v1/models/small", headers=first, json=model)
    assert configured.status_code == 200
    assert (await preview_client.get("/v1/models", headers=second)).json() == []
    assert len((await preview_client.get("/v1/models", headers=first)).json()) == 1
    listed = await preview_client.get("/v1/credentials", headers=first)
    assert "ciphertext" not in listed.text and "synthetic-provider-key" not in listed.text
    with store.engine.connect() as connection:
        ciphertext = connection.execute(select(schema.provider_credentials.c.ciphertext)).scalar_one()
        assert b"synthetic-provider-key" not in ciphertext
    rotated = await preview_client.put(f"/v1/credentials/{credential_id}", headers=first, json={"api_key": "rotated-provider-secret"})
    assert rotated.status_code == 200 and "rotated-provider-secret" not in rotated.text
    assert (await preview_client.delete(f"/v1/credentials/{credential_id}", headers=second)).status_code == 404
    assert (await preview_client.delete(f"/v1/credentials/{credential_id}", headers=first)).status_code == 204
    assert (await preview_client.get("/v1/models", headers=first)).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"provider": "custom", "label": "Test", "api_key": "secret-value"},
    {"provider": "openai", "label": "Test", "api_key": "bad\nsecret"},
    {"provider": "openai", "label": "Test", "api_key": "secret-value", "base_url": "http://127.0.0.1"},
])
async def test_credential_validation_redacts_input(preview_client: httpx.AsyncClient, payload: dict) -> None:
    """Reject unsupported providers/URLs and invalid secrets without echoing request values."""
    response = await preview_client.post("/v1/credentials", headers={"Authorization": "Bearer browser-first"}, json=payload)
    assert response.status_code == 422
    assert "secret" not in response.text and "base_url" not in response.text


@pytest.mark.asyncio
async def test_model_setup_requires_verified_owner(preview_client: httpx.AsyncClient) -> None:
    """Unverified sessions and ordinary SDK keys cannot store or rotate provider credentials."""
    payload = {"provider": "openai", "label": "Test", "api_key": "synthetic-provider-key"}
    assert (await preview_client.post("/v1/credentials", headers={"Authorization": "Bearer browser-unverified"}, json=payload)).status_code == 403
    key = await preview_client.post("/v1/api-keys", headers={"Authorization": "Bearer browser-first"}, json={"name": "SDK"})
    assert (await preview_client.post("/v1/credentials", headers={"Authorization": f"Bearer {key.json()['key']}"}, json=payload)).status_code == 403


async def _configure_http_model(client: httpx.AsyncClient) -> dict[str, str]:
    """Set up an owned model and return only its synthetic gateway authorization header."""
    headers = {"Authorization": "Bearer browser-first"}
    credential = await client.post("/v1/credentials", headers=headers, json={"provider": "openai", "label": "Inference", "api_key": "synthetic-provider-key"})
    assert credential.status_code == 201
    model = await client.put("/v1/models/small", headers=headers, json={
        "credential_id": credential.json()["id"], "model": "test-model",
        "input_price_per_1k": 1, "output_price_per_1k": 2,
    })
    assert model.status_code == 200
    key = await client.post("/v1/api-keys", headers=headers, json={"name": "Inference client"})
    assert key.status_code == 201
    return {"Authorization": f"Bearer {key.json()['key']}"}


@pytest.mark.asyncio
async def test_gateway_key_chat_and_testlab_are_scoped(
    preview_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real authenticated HTTP flow uses owned models and persists private attempts and run history."""
    headers = await _configure_http_model(preview_client)
    provider = AsyncMock(return_value=providers.Completion("Useful answer.", 10, 4, 5, "test-model", "stop", {"prompt_tokens": 10, "completion_tokens": 4}))
    monkeypatch.setattr(providers, "chat", provider)
    response = await preview_client.post("/v1/chat/completions", headers={**headers, "X-SmartRoute-Source": "sdk"}, json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })
    assert response.status_code == 200
    assert response.json()["model"] == "test-model"
    assert response.json()["smartroute"]["actual_cost_usd"] == pytest.approx(0.018)
    detail = await preview_client.get(f"/v1/requests/{response.json()['id']}", headers=headers)
    assert detail.json()["source"] == "sdk" and len(detail.json()["attempts"]) == 1
    assert "synthetic-provider-key" not in detail.text
    assert provider.await_args.args[3] == "synthetic-provider-key"
    other = {"Authorization": "Bearer browser-second"}
    assert (await preview_client.get(f"/v1/requests/{response.json()['id']}", headers=other)).status_code == 404
    run = await preview_client.post("/v1/testlab/run", headers=headers, json={"limit": 2})
    assert run.status_code == 200 and run.json()["prompt_count"] == 2
    assert (await preview_client.get("/v1/testlab/runs", headers=headers)).json()["total"] == 1
    assert (await preview_client.get("/v1/testlab/runs", headers=other)).json()["total"] == 0
    assert (await preview_client.get("/v1/requests", headers=headers)).json()["total"] == 3


@pytest.mark.asyncio
async def test_workspace_inference_concurrency(
    preview_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a second operation before provider execution and release capacity afterward."""
    headers = await _configure_http_model(preview_client)
    entered, release = asyncio.Event(), asyncio.Event()
    async def answer(*_args: Any, **_kwargs: Any) -> providers.Completion:
        """Pause one provider call deterministically without sleeps."""
        entered.set()
        await release.wait()
        return providers.Completion("Answer", 10, 2, 5, "test-model", "stop", {})
    monkeypatch.setattr(providers, "chat", answer)
    body = {"model": "smartroute/small", "messages": [{"role": "user", "content": "Hello"}]}
    running = asyncio.create_task(preview_client.post("/v1/chat/completions", headers=headers, json=body))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        overlapping = await preview_client.post("/v1/chat/completions", headers=headers, json=body)
        assert overlapping.status_code == 429
    finally:
        release.set()
        completed = await asyncio.wait_for(running, timeout=5)
    assert completed.status_code == 200
    assert (await preview_client.post("/v1/chat/completions", headers=headers, json=body)).status_code == 200


@pytest.mark.asyncio
async def test_source_sdk_onboarding_to_revocation(preview_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise source SDK setup, inference, feedback, isolation, and revocation against real routes."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "sdk" / "src"))
    from smartroute_client import OwnerSetup, SmartRoute, SmartRouteError

    loop = asyncio.get_running_loop()
    def gateway(request: httpx.Request) -> httpx.Response:
        """Bridge the synchronous SDK transport into the isolated authenticated ASGI app."""
        future = asyncio.run_coroutine_threadsafe(preview_client.request(
            request.method, request.url.raw_path.decode("ascii"), headers=dict(request.headers), content=request.content,
        ), loop)
        response = future.result(timeout=10)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    def setup_workspace() -> None:
        """Explicit owner setup stores a private model without any inference side effects."""
        with OwnerSetup("http://localhost:8001", "synthetic.owner.jwt", transport=httpx.MockTransport(gateway)) as owner:
            credential = owner.create_credential("openai", "SDK setup", "synthetic-provider-key")
            owner.configure_model("small", credential_id=credential["id"], model="test-small", input_price_per_1k=1, output_price_per_1k=2)
            assert "synthetic-provider-key" not in str(owner.credentials())

    await asyncio.to_thread(setup_workspace)
    owner_headers = {"Authorization": "Bearer browser-first"}
    first_key = (await preview_client.post("/v1/api-keys", headers=owner_headers, json={"name": "SDK integration"})).json()
    second_key = (await preview_client.post("/v1/api-keys", headers={"Authorization": "Bearer browser-second"}, json={"name": "Other workspace"})).json()
    provider = AsyncMock(return_value=providers.Completion("SDK answer", 10, 2, 5, "test-small", "stop", {}))
    monkeypatch.setattr(providers, "chat", provider)

    def exercise() -> None:
        """Use ordinary gateway keys for data operations, never provider administration."""
        with SmartRoute("http://localhost:8001", first_key["key"], transport=httpx.MockTransport(gateway)) as client:
            assert client.workspace()["auth_type"] == "api_key"
            assert len(client.models()) == 1
            result = client.chat("Hello", max_tokens=32)
            assert result.content == "SDK answer" and result.cost_usd == pytest.approx(0.014)
            assert client.feedback(result.request_id, good=True)["score"] == 1
            detail = client.request(result.request_id)
            assert detail["source"] == "sdk" and detail["feedback"] == 1 and len(detail["attempts"]) == 1
            assert client.requests(source="sdk")["total"] == 1
            with SmartRoute("http://localhost:8001", second_key["key"], transport=httpx.MockTransport(gateway)) as other:
                assert other.requests()["total"] == 0
                with pytest.raises(SmartRouteError) as denied:
                    other.request(result.request_id)
                assert denied.value.status_code == 404
                with pytest.raises(SmartRouteError) as denied_feedback:
                    other.feedback(result.request_id, good=False)
                assert denied_feedback.value.status_code == 404

    await asyncio.to_thread(exercise)
    assert (await preview_client.delete(f"/v1/api-keys/{first_key['id']}", headers=owner_headers)).status_code == 204
    def revoked() -> None:
        """The already issued SDK key loses access immediately after revocation."""
        with SmartRoute("http://localhost:8001", first_key["key"], transport=httpx.MockTransport(gateway)) as client:
            with pytest.raises(SmartRouteError) as denied:
                client.models()
            assert denied.value.status_code == 401
    await asyncio.to_thread(revoked)
    assert provider.await_count == 1