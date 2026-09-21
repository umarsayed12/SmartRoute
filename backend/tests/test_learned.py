"""Verify lazy model loading, stable feature order, replacement, and fallback."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import joblib
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app import db
from app.providers.base import ProviderResult
from app.routing import learned
from app.routing import router as routing_router
from app.routing.features import FEATURE_ORDER


def _save_model(path: Path, labels: tuple[str, str] = ("small", "medium")) -> None:
    """Store a tiny deterministic pipeline to exercise real artifact loading."""
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(max_iter=1000)),
    ])
    model.fit([[0.0] * len(FEATURE_ORDER), [10.0] * len(FEATURE_ORDER)], list(labels))
    joblib.dump(model, path)


def test_missing_model_falls_back() -> None:
    """A fresh installation needs no trained artifact to use heuristic routing."""
    assert learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0)) is None


def test_model_load_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use real probabilities while loading an unchanged artifact only once."""
    _save_model(learned.settings.MODEL_PATH)
    loader = Mock(wraps=joblib.load)
    monkeypatch.setattr(learned.joblib, "load", loader)

    first = learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0))
    second = learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 10.0))

    assert first is not None and second is not None
    assert first[0] == "small"
    assert second[0] == "medium"
    assert 0.5 < first[1] <= 1.0
    assert "probability" in first[2]
    loader.assert_called_once()


def test_replaced_and_removed_models() -> None:
    """Detect a new model without a restart and stop using one that was removed."""
    path = learned.settings.MODEL_PATH
    _save_model(path)
    original = learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0))
    assert original is not None and original[0] == "small"
    old_version = path.stat()
    _save_model(path, ("large", "medium"))
    os.utime(path, ns=(old_version.st_atime_ns, old_version.st_mtime_ns + 1_000_000))

    replaced = learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0))

    assert replaced is not None and replaced[0] == "large"
    path.unlink()
    assert learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0)) is None


def test_feature_order_is_not_dictionary_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vectorize by FEATURE_ORDER rather than by the caller's dictionary insertion order."""
    path = learned.settings.MODEL_PATH
    _save_model(path)
    model = joblib.load(path)
    prediction = Mock(wraps=model.predict_proba)
    monkeypatch.setattr(model, "predict_proba", prediction)
    monkeypatch.setattr(learned, "_load_model", Mock(return_value=model))
    features = {name: float(index) for index, name in reversed(list(enumerate(FEATURE_ORDER)))}

    assert learned.pick_tier(features) is not None
    prediction.assert_called_once_with([[float(index) for index in range(len(FEATURE_ORDER))]])


@pytest.mark.parametrize("artifact", ["corrupt", "wrong_type", "unknown_tiers"])
def test_invalid_model_falls_back(artifact: str) -> None:
    """Unreadable or incompatible local artifacts never disable the heuristic path."""
    path = learned.settings.MODEL_PATH
    if artifact == "corrupt":
        path.write_bytes(b"invalid joblib artifact")
    elif artifact == "wrong_type":
        joblib.dump({"unexpected": "payload"}, path)
    else:
        _save_model(path, ("unknown", "medium"))

    assert learned.pick_tier(dict.fromkeys(FEATURE_ORDER, 0.0)) is None


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub model execution while retaining the gateway's real routing and logging paths."""
    monkeypatch.setattr(routing_router.settings, "LARGE_MODEL", "")
    monkeypatch.setattr(routing_router.settings, "CONFIDENCE_THRESHOLD", 0.6)
    monkeypatch.setattr(routing_router.settings, "MAX_ESCALATIONS", 1)
    mocked = AsyncMock(return_value=ProviderResult(
        "A test answer.", 12, 3, 17, "test-model",
    ))
    monkeypatch.setattr(routing_router, "_call_tier", mocked)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=0.9))
    return mocked


@pytest.mark.asyncio
@pytest.mark.parametrize(("chosen", "final"), [
    ("small", "small"), ("medium", "medium"), ("large", "medium"),
])
async def test_learned_gateway_selection(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch,
    chosen: str, final: str,
) -> None:
    """Learned selection replaces the heuristic while retaining configured tier fallback."""
    predictor = Mock(return_value=(chosen, 0.97, "Learned prediction with probability 0.97."))
    heuristic = Mock(side_effect=AssertionError("A learned decision should skip the heuristic."))
    monkeypatch.setattr(learned, "pick_tier", predictor)
    monkeypatch.setattr(routing_router, "pick_tier", heuristic)

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    routing = response.json()["smartroute"]
    assert routing["tier_chosen"] == chosen
    assert routing["tier_final"] == final
    assert routing["routing_mode"] == "learned"
    assert routing["confidence"] == 0.9
    assert "0.97" in routing["reason"]
    assert provider.await_args.args[0].name == final
    assert db.get_request(response.json()["id"])["routing_mode"] == "learned"
    predictor.assert_called_once()
    heuristic.assert_not_called()


@pytest.mark.asyncio
async def test_learned_selection_still_escalates(
    client: httpx.AsyncClient, provider: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A high classification probability does not replace answer-confidence scoring."""
    monkeypatch.setattr(learned, "pick_tier", Mock(return_value=("small", 0.99, "Learned choice.")))
    monkeypatch.setattr(routing_router, "score", AsyncMock(side_effect=[0.1, 1.0]))

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    routing = response.json()["smartroute"]
    assert routing["routing_mode"] == "learned"
    assert routing["tier_chosen"] == "small"
    assert routing["tier_final"] == "medium"
    assert routing["escalated"] is True
    assert routing["confidence"] == 1.0
    assert [call.args[0].name for call in provider.await_args_list] == ["small", "medium"]


@pytest.mark.asyncio
async def test_corrupt_model_keeps_gateway_available(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """An invalid artifact produces a normal heuristic-routed response."""
    learned.settings.MODEL_PATH.write_bytes(b"invalid model")

    response = await client.post("/v1/chat/completions", json={
        "model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}],
    })

    assert response.status_code == 200
    assert response.json()["smartroute"]["routing_mode"] == "heuristic"
    provider.assert_awaited_once()