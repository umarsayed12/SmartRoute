"""Verify runtime settings, tier health, and training administration behavior."""

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from app import config, db
from app.api import admin
from app.config import RuntimeSettings
from app.main import app
from app.providers.base import ProviderResult
from app.routing import router as routing_router

MockHttp = Callable[[Callable[[httpx.Request], httpx.Response]], None]


def test_runtime_settings_defaults() -> None:
    """Expose only the editable, non-secret settings with their configured defaults."""
    assert config.get_runtime_settings().model_dump() == {
        "confidence_threshold": 0.6,
        "max_escalations": 1,
        "reference_input_price_per_1k": 0.0025,
        "reference_output_price_per_1k": 0.010,
        "routing_mode_preference": "auto",
    }


def test_settings_update_and_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist merged settings and restore them onto the same shared object after startup."""
    config.update_runtime_settings(RuntimeSettings(max_escalations=2))
    updated = config.update_runtime_settings(RuntimeSettings(confidence_threshold=0.8))
    path = config.settings.DB_PATH.with_name("settings.json")

    assert updated.max_escalations == 2
    assert updated.confidence_threshold == 0.8
    assert json.loads(path.read_text(encoding="utf-8")) == updated.model_dump()
    monkeypatch.setattr(config.settings, "CONFIDENCE_THRESHOLD", 0.3)
    monkeypatch.setattr(config.settings, "MAX_ESCALATIONS", 0)
    config.load_runtime_settings()
    assert config.settings.CONFIDENCE_THRESHOLD == 0.8
    assert config.settings.MAX_ESCALATIONS == 2


def test_failed_settings_write_preserves_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed disk write must not apply a setting that will disappear on restart."""
    before = config.get_runtime_settings()
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("simulated write failure")))

    with pytest.raises(OSError):
        config.update_runtime_settings(RuntimeSettings(confidence_threshold=0.9))

    assert config.get_runtime_settings() == before
    assert not config.settings.DB_PATH.with_name("settings.json").exists()


@pytest.mark.parametrize("content", ['not json', '{"confidence_threshold":2}', '{"unexpected":true}', b"\xff"])
def test_invalid_persisted_settings_are_ignored(content: str | bytes) -> None:
    """A corrupt settings file does not replace valid environment or memory values."""
    config.settings.DB_PATH.with_name("settings.json").write_bytes(
        content if isinstance(content, bytes) else content.encode("utf-8")
    )
    before = config.get_runtime_settings()

    config.load_runtime_settings()

    assert config.get_runtime_settings() == before


@pytest.mark.parametrize("values", [
    {"confidence_threshold": -0.1}, {"confidence_threshold": 1.1},
    {"max_escalations": -1}, {"max_escalations": True},
    {"reference_input_price_per_1k": -1}, {"reference_output_price_per_1k": float("inf")},
    {"reference_input_price_per_1k": float("nan")}, {"routing_mode_preference": "unknown"},
    {"LARGE_API_KEY": "not-an-editable-setting"},
])
def test_invalid_runtime_settings(values: dict[str, object]) -> None:
    """Reject invalid limits, non-finite prices, and fields outside the editable set."""
    with pytest.raises(ValidationError):
        RuntimeSettings(**values)


@pytest.mark.asyncio
async def test_startup_restores_settings() -> None:
    """Application startup applies the persisted override before serving requests."""
    config.settings.DB_PATH.with_name("settings.json").write_text(
        '{"confidence_threshold":0.77,"routing_mode_preference":"heuristic_only"}', encoding="utf-8"
    )

    async with app.router.lifespan_context(app):
        assert config.settings.CONFIDENCE_THRESHOLD == 0.77
        assert config.settings.ROUTING_MODE_PREFERENCE == "heuristic_only"
        assert config.settings.MAX_ESCALATIONS == 1


@pytest.mark.asyncio
async def test_settings_api_round_trip(client: httpx.AsyncClient) -> None:
    """GET returns a safe snapshot and PUT merges only the fields supplied."""
    initial = await client.get("/v1/settings")
    assert initial.status_code == 200
    assert set(initial.json()) == set(RuntimeSettings.model_fields)

    updated = await client.put("/v1/settings", json={"max_escalations": 2})
    assert updated.status_code == 200
    assert updated.json()["max_escalations"] == 2
    current = await client.get("/v1/settings")
    assert current.json() == updated.json()
    assert current.json()["confidence_threshold"] == initial.json()["confidence_threshold"]
    saved = json.loads(config.settings.DB_PATH.with_name("settings.json").read_text(encoding="utf-8"))
    assert saved == updated.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"confidence_threshold": 2}, {"max_escalations": -1},
    {"reference_input_price_per_1k": -1}, {"routing_mode_preference": "invalid"},
    {"LARGE_API_KEY": "not-editable"},
])
async def test_settings_api_validation(client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    """Invalid updates are rejected without changing memory or writing a settings file."""
    before = config.get_runtime_settings()

    response = await client.put("/v1/settings", json=payload)

    assert response.status_code == 422
    assert config.get_runtime_settings() == before
    assert not config.settings.DB_PATH.with_name("settings.json").exists()


@pytest.mark.asyncio
async def test_settings_api_write_failure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persistence errors produce a controlled response and retain previous runtime values."""
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("private filesystem detail")))

    response = await client.put("/v1/settings", json={"confidence_threshold": 0.9})

    assert response.status_code == 500
    assert "private filesystem detail" not in response.text
    assert config.settings.CONFIDENCE_THRESHOLD == 0.6


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Keep real configuration and routing while replacing only model execution."""
    mocked = AsyncMock(return_value=ProviderResult("Test answer", 10, 4, 5, "test-model"))
    monkeypatch.setattr(routing_router, "_call_tier", mocked)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=1.0))
    return mocked


@pytest.mark.asyncio
@pytest.mark.parametrize(("preference", "expected_mode", "expected_tier"), [
    ("auto", "learned", "medium"),
    ("heuristic_only", "heuristic", "small"),
    ("learned_only", "learned", "medium"),
])
async def test_runtime_routing_preference(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    preference: str, expected_mode: str, expected_tier: str,
) -> None:
    """Changing the preference affects the next request without reloading the app."""
    predictor = Mock(return_value=("medium", 0.8, "Learned prediction."))
    monkeypatch.setattr(routing_router.learned, "pick_tier", predictor)
    updated = await client.put("/v1/settings", json={"routing_mode_preference": preference})
    assert updated.status_code == 200

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    assert response.json()["smartroute"]["routing_mode"] == expected_mode
    assert response.json()["smartroute"]["tier_chosen"] == expected_tier
    assert predictor.call_count == (0 if preference == "heuristic_only" else 1)


@pytest.mark.asyncio
async def test_learned_only_unavailable_and_forced_override(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Learned-only fails clearly without a model, but explicit fixed-tier requests still work."""
    await client.put("/v1/settings", json={"routing_mode_preference": "learned_only"})
    payload = {"model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}]}

    unavailable = await client.post("/v1/chat/completions", json=payload)

    assert unavailable.status_code == 503
    assert "trained model" in unavailable.json()["detail"]
    provider.assert_not_awaited()
    assert db.list_requests()["total"] == 0
    forced = await client.post("/v1/chat/completions", json={**payload, "model": "smartroute/small"})
    assert forced.status_code == 200
    assert forced.json()["smartroute"]["routing_mode"] == "forced"


@pytest.mark.asyncio
async def test_runtime_budget_and_reference_prices(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updated budgets and reference prices are consumed by the real router."""
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=0.1))
    response = await client.put("/v1/settings", json={
        "max_escalations": 0, "reference_input_price_per_1k": 1.0,
        "reference_output_price_per_1k": 2.0,
    })
    assert response.status_code == 200

    completion = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert completion.status_code == 200
    assert completion.json()["smartroute"]["escalated"] is False
    assert completion.json()["smartroute"]["reference_cost_usd"] == pytest.approx(0.018)
    provider.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("base_suffix", ["", "/v1/"])
async def test_tier_reachability_and_secret_redaction(
    client: httpx.AsyncClient, mock_http: MockHttp, monkeypatch: pytest.MonkeyPatch,
    base_suffix: str,
) -> None:
    """Probe model lists with the right URL and auth while never returning bearer keys."""
    monkeypatch.setattr(config.settings, "OLLAMA_BASE_URL", "http://ollama.test")
    monkeypatch.setattr(config.settings, "LARGE_MODEL", "example-large")
    monkeypatch.setattr(config.settings, "LARGE_BASE_URL", f"https://remote.test{base_suffix}")
    monkeypatch.setattr(config.settings, "LARGE_API_KEY", config.SecretStr("test-only-key"))

    def handle(request: httpx.Request) -> httpx.Response:
        """Return available model lists and verify no inference calls are made."""
        assert request.method == "GET"
        if request.url.host == "ollama.test":
            assert request.url.path == "/api/tags"
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})
        assert str(request.url) == "https://remote.test/v1/models"
        assert request.headers["Authorization"] == "Bearer test-only-key"
        return httpx.Response(200, json={"data": [{"id": "example-large"}]})

    mock_http(handle)
    response = await client.get("/v1/tiers")

    assert response.status_code == 200
    tiers = response.json()
    assert [tier["name"] for tier in tiers] == ["small", "medium", "large"]
    assert [tier["reachable"] for tier in tiers] == [True, False, True]
    assert all(tier["enabled"] for tier in tiers)
    assert "api_key" not in response.text
    assert "test-only-key" not in response.text
    assert tiers[0]["input_price_per_1k"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "http_error", "invalid_json"])
async def test_unreachable_and_disabled_tiers(
    client: httpx.AsyncClient, mock_http: MockHttp, monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Report failed providers as unavailable and avoid probing a disabled large tier."""
    monkeypatch.setattr(config.settings, "LARGE_MODEL", "")

    def handle(request: httpx.Request) -> httpx.Response:
        """Simulate unsuccessful Ollama probes without a remote request."""
        assert request.url.path == "/api/tags"
        if failure == "timeout":
            raise httpx.ReadTimeout("unavailable", request=request)
        if failure == "http_error":
            return httpx.Response(503)
        return httpx.Response(200, text="not json")

    mock_http(handle)
    response = await client.get("/v1/tiers")

    assert response.status_code == 200
    assert all(not tier["reachable"] for tier in response.json())
    assert response.json()[2]["enabled"] is False


@pytest.mark.asyncio
async def test_training_skip_and_status(client: httpx.AsyncClient) -> None:
    """The real trainer reports insufficient data normally through the admin endpoint."""
    status = await client.get("/v1/train/status")
    response = await client.post("/v1/train")

    assert status.json() == {"trained": False}
    assert response.status_code == 200
    assert response.json()["trained"] is False
    assert response.json()["n_rows"] == 0
    assert not config.settings.MODEL_PATH.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_metadata", [b"invalid", b"\xff"])
async def test_training_metadata_status(client: httpx.AsyncClient, invalid_metadata: bytes) -> None:
    """Return saved metrics only when the corresponding artifact and valid metadata exist."""
    metadata = {
        "trained": True, "trained_at": "2026-09-21T12:00:00Z", "n_rows": 30,
        "accuracy": 1.0, "classes": ["small", "medium"],
        "confusion_matrix": [[3, 0], [0, 3]], "evaluation": "holdout",
    }
    config.settings.MODEL_PATH.with_name("router_model_meta.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    missing = await client.get("/v1/train/status")
    assert missing.json() == {"trained": False}
    config.settings.MODEL_PATH.write_bytes(b"artifact presence check")

    response = await client.get("/v1/train/status")

    assert response.status_code == 200
    assert response.json() == metadata
    config.settings.MODEL_PATH.with_name("router_model_meta.json").write_bytes(invalid_metadata)
    invalid = await client.get("/v1/train/status")
    assert invalid.json() == {"trained": False}


@pytest.mark.asyncio
async def test_training_conflict_and_error_release(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject overlapping jobs and release the training lock after a failed attempt."""
    trainer = Mock(side_effect=OSError("private training path"))
    monkeypatch.setattr(admin.training, "train", trainer)
    with admin._training_lock:
        conflict = await client.post("/v1/train")
    assert conflict.status_code == 409
    trainer.assert_not_called()

    failed = await client.post("/v1/train")
    assert failed.status_code == 500
    assert "private training path" not in failed.text
    trainer.side_effect = None
    trainer.return_value = {"trained": True, "n_rows": 30, "accuracy": 1.0}
    success = await client.post("/v1/train")
    assert success.status_code == 200
    assert success.json() == trainer.return_value