"""Verify benchmark HTTP requests, report scope, CLI output, and failure behavior."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import benchmark


def _run(mode: str) -> dict[str, Any]:
    """Build a minimal measured-run response for testing the report writer."""
    return {
        "mode": mode, "prompt_count": 2,
        "results": [
            {"id": "simple-01", "tier_final": "small" if mode == "auto" else "medium"},
            {"id": "simple-02", "tier_final": "medium"},
        ],
        "summary": {
            "routing_accuracy": 0.5 if mode == "auto" else 0.0,
            "escalation_rate": 0.5 if mode == "auto" else 0.0,
            "avg_latency_ms": 123.4, "total_actual_usd": 0.01,
            "total_reference_usd": 0.04, "saved_pct": 75.0,
        },
    }


@pytest.mark.parametrize("limit", [None, 2])
def test_benchmark_calls_both_modes(limit: int | None) -> None:
    """Use the same endpoint and requested prefix for both comparison modes."""
    payloads: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Validate the benchmark API call and return synthetic measured data."""
        assert request.method == "POST"
        assert str(request.url) == "http://gateway.test/v1/testlab/run"
        payload = json.loads(request.content)
        payloads.append(payload)
        return httpx.Response(200, json=_run(payload["mode"]))

    with httpx.Client(base_url="http://gateway.test/", transport=httpx.MockTransport(handle)) as client:
        runs = benchmark.run_benchmark(client, limit)

    assert [payload["mode"] for payload in payloads] == ["auto", "large"]
    assert all(payload["suite"] == "default" for payload in payloads)
    assert all(payload.get("limit") == limit for payload in payloads)
    assert [run["mode"] for run in runs] == ["auto", "large"]


def test_report_scope_and_metrics() -> None:
    """Expose measured percentages and fallback caveats without claiming answer quality."""
    report = benchmark.format_report([_run("auto"), _run("large")], limit=2)

    assert report.startswith("<!--")
    assert "first 2 prompts" in report
    assert "Prompts per mode: 2" in report
    assert "| auto | 50.0% | 50.0% | 123.4 | 0.010000 | 0.040000 | 75.0% |" in report
    assert "medium: 2" in report
    assert "not answer correctness" in report
    assert "large-only resolves to medium" in report


def test_cli_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI prints and writes the report after two successful HTTP runs."""
    original_client = httpx.Client

    def handle(request: httpx.Request) -> httpx.Response:
        """Return a complete response for each selected mode."""
        return httpx.Response(200, json=_run(json.loads(request.content)["mode"]))

    def create_client(**kwargs: Any) -> httpx.Client:
        """Keep the CLI's URL and timeout options while replacing network transport."""
        return original_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(benchmark.httpx, "Client", create_client)
    output = tmp_path / "reports" / "benchmark.md"

    benchmark.main(["--base-url", "http://gateway.test", "--limit", "2", "--output", str(output)])

    assert "first 2 prompts" in output.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert "Running auto" in printed and "Running large" in printed
    assert "Report written to" in printed


def test_cli_failure_preserves_previous_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed suite does not replace an earlier measured report with partial results."""
    original_client = httpx.Client

    def create_client(**kwargs: Any) -> httpx.Client:
        """Return a controlled failed response without contacting a gateway."""
        return original_client(**kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(503)))

    monkeypatch.setattr(benchmark.httpx, "Client", create_client)
    output = tmp_path / "benchmark.md"
    output.write_text("previous report", encoding="utf-8")

    with pytest.raises(SystemExit, match="Benchmark failed"):
        benchmark.main(["--output", str(output)])

    assert output.read_text(encoding="utf-8") == "previous report"


@pytest.mark.parametrize("limit", ["0", "41", "not-a-number"])
def test_invalid_cli_limit(limit: str) -> None:
    """Reject invalid limits before connecting to the gateway."""
    with pytest.raises(SystemExit) as caught:
        benchmark.main(["--limit", limit])

    assert caught.value.code == 2