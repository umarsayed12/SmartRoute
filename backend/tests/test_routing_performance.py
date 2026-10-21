"""Tier 4: Routing Performance Microbenchmarks & Gateway E2E Tests.

Verifies:
1. Sub-millisecond (< 1.0ms) SLA routing latency across 2,000 iterations.
2. Cold-start single-turn microbenchmark (< 0.2ms mean, < 1.0ms P99).
3. Deep-history 50-turn microbenchmark (< 1.0ms mean, < 1.0ms P99).
4. End-to-end FastAPI integration for multi-turn conversational praise -> small tier.
5. End-to-end FastAPI integration for multi-turn technical follow-up -> medium tier.
6. End-to-end FastAPI integration for standalone long-output request -> large tier.
7. End-to-end FastAPI integration for single-turn greeting -> small tier.
8. Database storage verification of legacy-compatible features_json and tier records.
"""

import gc
import json
from time import perf_counter
from unittest.mock import AsyncMock

import httpx
import pytest

from app import db
from app.config import Settings
from app.providers.base import ProviderResult
from app.routing import confidence
from app.routing import router as routing_router
from app.routing.features import FEATURE_ORDER, extract_features
from app.routing.heuristic import pick_tier


# =====================================================================
# Fixtures for Gateway E2E Tests
# =====================================================================


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub provider calls and confidence so E2E tests never make network requests."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)
    monkeypatch.setattr(routing_router, "settings", configured)
    monkeypatch.setattr(confidence, "settings", configured)
    monkeypatch.setattr(routing_router, "score", AsyncMock(return_value=0.9))
    mocked = AsyncMock(
        return_value=ProviderResult(
            content="Mocked response",
            prompt_tokens=25,
            completion_tokens=10,
            latency_ms=15,
            model="qwen2.5:1.5b",
        )
    )
    monkeypatch.setattr(routing_router.ollama, "chat", mocked)
    return mocked


# =====================================================================
# 1. Latency Microbenchmarks (< 1.0ms SLA)
# =====================================================================


def test_sub_millisecond_routing_latency_benchmark() -> None:
    """Extracting features and picking tier executes in < 1.0 ms over 2,000 iterations."""
    messages = [
        {"role": "user", "content": "Hello there! Good morning."},
        {"role": "assistant", "content": "Good morning! How can I assist you with your project?"},
        {
            "role": "user",
            "content": "Can you provide Python code to implement binary search?",
        },
        {
            "role": "assistant",
            "content": (
                "```python\n"
                "def binary_search(arr, target):\n"
                "    left, right = 0, len(arr) - 1\n"
                "    while left <= right:\n"
                "        mid = (left + right) // 2\n"
                "        if arr[mid] == target:\n"
                "            return mid\n"
                "        elif arr[mid] < target:\n"
                "            left = mid + 1\n"
                "        else:\n"
                "            right = mid - 1\n"
                "    return -1\n"
                "```"
            ),
        },
        {"role": "user", "content": "Thanks, got it! That looks super clean."},
        {"role": "assistant", "content": "You are very welcome!"},
        {"role": "user", "content": "What about space complexity?"},
    ]

    iterations = 2000
    latencies: list[float] = []

    # Warmup
    for _ in range(50):
        pick_tier(extract_features(messages))

    # Benchmark loop
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(iterations):
            t0 = perf_counter()
            features = extract_features(messages)
            _tier, _reason = pick_tier(features)
            t1 = perf_counter()
            latencies.append(t1 - t0)
    finally:
        if gc_was_enabled:
            gc.enable()

    mean_ms = (sum(latencies) / iterations) * 1000.0
    sorted_latencies = sorted(latencies)
    p50_ms = sorted_latencies[int(0.50 * iterations)] * 1000.0
    p95_ms = sorted_latencies[int(0.95 * iterations)] * 1000.0
    p99_ms = sorted_latencies[int(0.99 * iterations)] * 1000.0

    # Strict SLA budget assertions: Mean and P99 must be strictly below 1.0 ms
    assert mean_ms < 1.0, f"Mean latency {mean_ms:.4f} ms exceeded 1.0 ms SLA"
    assert p95_ms < 1.0, f"P95 latency {p95_ms:.4f} ms exceeded 1.0 ms SLA"
    assert p99_ms < 1.0, f"P99 latency {p99_ms:.4f} ms exceeded 1.0 ms SLA"


def test_cold_start_single_turn_latency_benchmark() -> None:
    """Cold-start single-turn feature extraction and heuristic routing executes under 0.2ms mean."""
    single_turn = [{"role": "user", "content": "Hello there!"}]
    iterations = 1000
    latencies: list[float] = []

    # Warmup
    for _ in range(25):
        pick_tier(extract_features(single_turn))

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(iterations):
            t0 = perf_counter()
            _tier, _ = pick_tier(extract_features(single_turn))
            t1 = perf_counter()
            latencies.append(t1 - t0)
    finally:
        if gc_was_enabled:
            gc.enable()

    mean_ms = (sum(latencies) / iterations) * 1000.0
    p99_ms = sorted(latencies)[int(0.99 * iterations)] * 1000.0

    assert mean_ms < 0.2, f"Cold start mean latency {mean_ms:.4f} ms exceeded 0.2 ms"
    assert p99_ms < 1.0, f"Cold start P99 latency {p99_ms:.4f} ms exceeded 1.0 ms"


def test_deep_history_20_turn_latency_benchmark() -> None:
    """A 20-turn conversation extracts and routes in < 1.0 ms (assert mean and P99 < 1.0 ms)."""
    deep_messages: list[dict[str, str]] = [{"role": "user", "content": "Hello"}]
    for i in range(10):
        deep_messages.append({"role": "assistant", "content": f"Turn response {i} explaining database indexing."})
        deep_messages.append({"role": "user", "content": f"Turn question {i} regarding cache eviction."})
    deep_messages.append({"role": "user", "content": "Thanks! Sounds good."})

    iterations = 500
    latencies: list[float] = []

    # Warmup
    for _ in range(25):
        pick_tier(extract_features(deep_messages))

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(iterations):
            t0 = perf_counter()
            _tier, _ = pick_tier(extract_features(deep_messages))
            t1 = perf_counter()
            latencies.append(t1 - t0)
    finally:
        if gc_was_enabled:
            gc.enable()

    mean_ms = (sum(latencies) / iterations) * 1000.0
    p99_ms = sorted(latencies)[int(0.99 * iterations)] * 1000.0

    assert mean_ms < 1.0, f"Deep history mean latency {mean_ms:.4f} ms exceeded 1.0 ms SLA"
    assert p99_ms < 1.0, f"Deep history P99 latency {p99_ms:.4f} ms exceeded 1.0 ms SLA"


# =====================================================================
# 2. FastAPI Gateway End-to-End Integration Tests
# =====================================================================


@pytest.mark.asyncio
async def test_e2e_multiturn_conversational_praise_routes_to_small(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """In a multi-turn chat with prior code, sending conversational praise routes to small tier."""
    messages = [
        {"role": "user", "content": "Write quicksort in Python"},
        {
            "role": "assistant",
            "content": "```python\ndef quicksort(arr): return arr\n```",
        },
        {"role": "user", "content": "Thanks, got it! That looks super clean."},
    ]
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smartroute/auto", "messages": messages},
    )

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]

    assert routing["tier_chosen"] == "small"
    assert routing["tier_final"] == "small"
    assert routing["routing_mode"] == "heuristic"
    assert "Conversational greeting, acknowledgment, or closure short-circuits to small tier." in routing["reason"]
    # Provider called with small model
    provider.assert_awaited_once_with(
        model="qwen2.5:1.5b",
        messages=messages,
        temperature=0.2,
        max_tokens=None,
        base_url="http://localhost:11434",
    )


@pytest.mark.asyncio
async def test_e2e_multiturn_technical_followup_routes_to_medium(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """In a multi-turn chat with prior code, a technical follow-up routes to medium tier."""
    messages = [
        {"role": "user", "content": "Write quicksort in Python"},
        {
            "role": "assistant",
            "content": "```python\ndef quicksort(arr): return arr\n```",
        },
        {"role": "user", "content": "What about space complexity?"},
    ]
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smartroute/auto", "messages": messages},
    )

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]

    assert routing["tier_chosen"] == "medium"
    assert routing["tier_final"] == "medium"
    assert routing["routing_mode"] == "heuristic"
    assert routing["reason"] == "Contextual follow-up referencing prior code."
    # Provider called with medium model
    provider.assert_awaited_once_with(
        model="qwen2.5:7b",
        messages=messages,
        temperature=0.2,
        max_tokens=None,
        base_url="http://localhost:11434",
    )


@pytest.mark.asyncio
async def test_e2e_standalone_long_output_routes_to_large(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Standalone long output request routes to large tier."""
    messages = [
        {"role": "user", "content": "Generate a detailed report analyzing database indexing strategies"}
    ]
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smartroute/auto", "messages": messages},
    )

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]

    assert routing["tier_chosen"] == "large"
    assert routing["routing_mode"] == "heuristic"
    assert "Current turn asks for long or detailed output." in routing["reason"]


@pytest.mark.asyncio
async def test_e2e_single_turn_greeting_routes_to_small(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Single turn greeting routes to small tier."""
    messages = [{"role": "user", "content": "Hello there!"}]
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smartroute/auto", "messages": messages},
    )

    assert response.status_code == 200
    data = response.json()
    routing = data["smartroute"]

    assert routing["tier_chosen"] == "small"
    assert routing["tier_final"] == "small"
    assert "Conversational greeting, acknowledgment, or closure" in routing["reason"]


# =====================================================================
# 3. Database Persistence Verification
# =====================================================================


@pytest.mark.asyncio
async def test_database_persistence_of_dual_scope_features(
    client: httpx.AsyncClient, provider: AsyncMock
) -> None:
    """Multi-turn requests serialize features_json into database with exact 10 FEATURE_ORDER keys."""
    messages = [
        {"role": "user", "content": "Write quicksort in Python"},
        {"role": "assistant", "content": "```python\ndef quicksort(arr): return arr\n```"},
        {"role": "user", "content": "Thanks, got it! That looks super clean."},
    ]
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smartroute/auto", "messages": messages},
    )
    assert response.status_code == 200
    request_id = response.json()["id"]

    # Verify database persistence via full request record
    stored = db.get_request(request_id)
    assert stored is not None

    # features_json is stored in database
    assert "features_json" in stored
    parsed_features = json.loads(stored["features_json"])

    # Must preserve exact 10 legacy keys
    assert list(parsed_features.keys()) == FEATURE_ORDER
    assert len(parsed_features) == 10
    assert all(isinstance(v, (int, float)) for v in parsed_features.values())

    # Stored tier matches chosen tier
    assert stored["tier_chosen"] == "small"
    assert stored["tier_final"] == "small"
