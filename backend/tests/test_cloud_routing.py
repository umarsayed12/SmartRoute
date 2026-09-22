"""Verify owned-model cascades, provider usage auditing, and absence of shared fallbacks."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import RuntimeSettings
from app.hosted.config import HostedSettings
from app.hosted.identity import Identity
from app.hosted.models import CredentialCreate, ModelConfiguration
from app.hosted.routing import HostedChatRequest, RoutingFailure, route_and_log
from app.hosted.store import Principal, WorkspaceStore


@pytest.fixture
def configured() -> HostedSettings:
    """Use a test-only encryption key without reading local provider credentials."""
    return HostedSettings(_env_file=None, PROVIDER_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"))


def _actor(store: WorkspaceStore, name: str = "first") -> Principal:
    """Provision a verified isolated identity for routing tests."""
    return store.provision(Identity("https://auth.example.test", name, f"{name}@example.test", name, True))


def _model(store: WorkspaceStore, actor: Principal, configured: HostedSettings, tier: str, provider: str = "openai") -> None:
    """Configure one owned model with explicit token prices."""
    credential = store.create_credential(actor, CredentialCreate(provider=provider, label=tier, api_key="synthetic-provider-key"), configured)
    store.configure_model(actor, tier, ModelConfiguration(
        credential_id=UUID(credential["id"]), model=f"test-{tier}",
        input_price_per_1k="1", output_price_per_1k="2",
    ))


@pytest.mark.asyncio
async def test_owned_cascade_audits_self_check_and_cost(store: WorkspaceStore, configured: HostedSettings) -> None:
    """A low small-tier score escalates to native Anthropic and logs every billed call."""
    actor = _actor(store)
    _model(store, actor, configured, "small")
    _model(store, actor, configured, "medium", "anthropic")
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Supply answer/check/answer responses with known provider usage."""
        payload = json.loads(request.content)
        calls.append((request.url.host, payload))
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, json={"model": "test-medium", "content": [{"type": "text", "text": "A complete answer."}], "usage": {"input_tokens": 30, "output_tokens": 10}})
        checking = payload["max_completion_tokens"] == 256
        return httpx.Response(200, json={"model": "test-small", "choices": [{"message": {"content": "0" if checking else "I don't know."}}], "usage": {"prompt_tokens": 20 if checking else 10, "completion_tokens": 1 if checking else 4}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response = await route_and_log(actor, store, configured, client, HostedChatRequest(model="smartroute/auto", messages=[{"role": "user", "content": "Hello"}]), "sdk")
    assert response.smartroute.escalated is True
    assert response.smartroute.tier_chosen == "small" and response.smartroute.tier_final == "medium"
    assert response.smartroute.actual_cost_usd == pytest.approx(0.09)
    assert response.usage.total_tokens == 40
    stored = store.get_request(actor, response.id)
    assert stored["status"] == "completed"
    assert [attempt["kind"] for attempt in stored["attempts"]] == ["answer", "self_check", "answer"]
    assert all(attempt["status"] == "completed" for attempt in stored["attempts"])
    assert [host for host, _payload in calls] == ["api.openai.com", "api.openai.com", "api.anthropic.com"]
    assert store.get_request(_actor(store, "second"), response.id) is None


@pytest.mark.asyncio
async def test_single_model_resolution_and_forced_tier_guard(store: WorkspaceStore, configured: HostedSettings) -> None:
    """Auto may resolve to the only owned model; an absent forced tier never silently falls back."""
    actor = _actor(store)
    _model(store, actor, configured, "medium")
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Return one answer for the only enabled tier."""
        calls.append(request)
        return httpx.Response(200, json={"model": "test-medium", "choices": [{"message": {"content": "Hello!"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await route_and_log(actor, store, configured, client, HostedChatRequest(model="smartroute/auto", messages=[{"role": "user", "content": "Hi"}]), "playground")
        with pytest.raises(RoutingFailure, match="forced tier"):
            await route_and_log(actor, store, configured, client, HostedChatRequest(model="smartroute/large", messages=[{"role": "user", "content": "Hi"}]), "sdk")
    assert result.smartroute.tier_final == "medium"
    assert "owned medium" in result.smartroute.reason
    assert result.smartroute.escalated is False and len(calls) == 1


@pytest.mark.asyncio
async def test_failed_provider_is_logged_without_zero_cost_claim(store: WorkspaceStore, configured: HostedSettings) -> None:
    """Timeouts retain an audit trail with unknown cost and are excluded from savings/training."""
    actor = _actor(store)
    _model(store, actor, configured, "small")
    def handle(request: httpx.Request) -> httpx.Response:
        """Simulate a request whose provider-side billing outcome is unknown."""
        raise httpx.ReadTimeout("private upstream detail", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RoutingFailure) as caught:
            await route_and_log(actor, store, configured, client, HostedChatRequest(model="smartroute/auto", messages=[{"role": "user", "content": "Hi"}]), "api")
    assert caught.value.status == 504 and caught.value.request_id
    row = store.get_request(actor, caught.value.request_id)
    assert row["status"] == "failed" and row["actual_cost_usd"] is None
    assert row["attempts"][0]["cost_usd"] is None
    assert row["attempts"][0]["error_code"] == "provider_timeout"
    assert not store.set_feedback(actor, row["id"], 1, None)
    now = datetime.now(timezone.utc)
    assert store.stats_rows(actor, now - timedelta(days=1), now + timedelta(days=1)) == []
    assert store.training_rows(actor) == []


@pytest.mark.asyncio
async def test_missing_models_and_learned_only_do_not_call_provider(store: WorkspaceStore, configured: HostedSettings) -> None:
    """Missing workspace configuration never uses process-global credentials or local models."""
    actor = _actor(store)
    def handle(request: httpx.Request) -> httpx.Response:
        """Fail if a configuration error reaches any inference endpoint."""
        raise AssertionError("Unexpected provider call")
    request = HostedChatRequest(model="smartroute/auto", messages=[{"role": "user", "content": "Hi"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RoutingFailure, match="at least one"):
            await route_and_log(actor, store, configured, client, request, "sdk")
        _model(store, actor, configured, "small")
        store.update_settings(actor, RuntimeSettings(routing_mode_preference="learned_only"))
        with pytest.raises(RoutingFailure, match="Learned-only"):
            await route_and_log(actor, store, configured, client, request, "sdk")
    assert store.list_requests(actor)["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("check_result", ["unparseable", "timeout"])
async def test_self_check_outcomes_are_audited(store: WorkspaceStore, configured: HostedSettings, check_result: str) -> None:
    """Record a neutral parse fallback or fail with unknown cumulative cost on checker timeout."""
    actor = _actor(store)
    _model(store, actor, configured, "small")
    _model(store, actor, configured, "medium")
    def handle(request: httpx.Request) -> httpx.Response:
        """Return an answer followed by a bounded checker outcome."""
        checking = json.loads(request.content)["max_completion_tokens"] == 256
        if checking and check_result == "timeout":
            raise httpx.ReadTimeout("private detail", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Not an integer" if checking else "Answer"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    request = HostedChatRequest(model="smartroute/small", messages=[{"role": "user", "content": "Hello"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        if check_result == "timeout":
            with pytest.raises(RoutingFailure) as caught:
                await route_and_log(actor, store, configured, client, request, "sdk")
            row = store.get_request(actor, caught.value.request_id)
            assert row["status"] == "failed" and row["actual_cost_usd"] is None
            assert row["attempts"][0]["cost_usd"] == pytest.approx(0.014)
            assert row["attempts"][1]["error_code"] == "provider_timeout"
        else:
            result = await route_and_log(actor, store, configured, client, request, "sdk")
            row = store.get_request(actor, result.id)
            assert row["actual_cost_usd"] == pytest.approx(0.028)
            assert row["attempts"][1]["usage_details"]["self_check"] == {"score": 0.5, "parse_status": "neutral_fallback"}


@pytest.mark.asyncio
async def test_cancellation_preserves_unknown_cost_attempt(store: WorkspaceStore, configured: HostedSettings) -> None:
    """Task cancellation records the in-flight provider attempt before cancellation escapes."""
    actor = _actor(store)
    _model(store, actor, configured, "small")
    entered, release = asyncio.Event(), asyncio.Event()
    async def handle(request: httpx.Request) -> httpx.Response:
        """Hold the transport until the routing task is cancelled."""
        entered.set()
        await release.wait()
        raise AssertionError("Cancelled transport unexpectedly resumed")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        task = asyncio.create_task(route_and_log(actor, store, configured, client, HostedChatRequest(model="smartroute/auto", messages=[{"role": "user", "content": "Hi"}]), "sdk"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    records = store.list_requests(actor)
    assert records["total"] == 1
    row = store.get_request(actor, records["items"][0]["id"])
    assert row["status"] == "failed" and row["actual_cost_usd"] is None
    assert row["attempts"][0]["error_code"] == "request_cancelled"


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": "Hello", "tool_calls": []}],
    [{"role": "tool", "content": "Hello"}],
    [{"role": "assistant", "content": "No user message"}],
    [{"role": "user", "content": "x" * 64000}, {"role": "user", "content": "x"}],
])
def test_unsupported_conversations_are_rejected(messages: list[dict[str, object]]) -> None:
    """Do not silently drop unsupported message fields or accept unbounded conversations."""
    with pytest.raises(ValidationError):
        HostedChatRequest(model="smartroute/auto", messages=messages)