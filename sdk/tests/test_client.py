"""Verify gateway headers, parsing, private history access, and secret-safe failure behavior."""

import json

import httpx
import pytest

from smartroute_client import OwnerSetup, SmartRoute, SmartRouteError, cli

KEY = "sr_" + "a" * 43
REQUEST_ID = "chatcmpl-" + "b" * 32


def completion() -> dict:
    """Return a synthetic response with cumulative, not final-call-only, cost."""
    return {"id": REQUEST_ID, "choices": [{"message": {"content": "Answer"}}],
            "smartroute": {"request_id": REQUEST_ID, "tier_final": "medium", "escalated": True,
                          "confidence": 0.8, "actual_cost_usd": 0.03, "reference_cost_usd": 0.05}}


@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/"])
def test_chat_contract(suffix: str) -> None:
    """Normalize API roots, authenticate once, and preserve source and generation options."""
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Inspect the SDK's wire contract without contacting a gateway."""
        calls.append(request)
        assert str(request.url) == "https://gateway.example.test/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.headers["x-smartroute-source"] == "sdk"
        assert json.loads(request.content) == {"model": "smartroute/auto", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 64}
        return httpx.Response(200, json=completion())
    with SmartRoute("https://gateway.example.test" + suffix, KEY, transport=httpx.MockTransport(handle)) as client:
        assert calls == []
        result = client.chat("Hello", max_tokens=64)
    assert result.content == "Answer" and result.tier == "medium" and result.escalated
    assert result.cost_usd == 0.03 and result.saved_usd == pytest.approx(0.02)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [302, 401, 403, 409, 429, 502, 504])
def test_errors_do_not_echo_secrets_or_retry(status: int) -> None:
    """Do not leak error details or follow a redirect that could forward credentials."""
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Return an intentionally unsafe body and redirect target."""
        calls.append(request)
        return httpx.Response(status, json={"detail": KEY, "request_id": REQUEST_ID}, headers={"location": "https://other.example.test"})
    with SmartRoute("https://gateway.example.test", KEY, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SmartRouteError) as caught:
            client.chat("Hello")
    assert caught.value.status_code == status and caught.value.request_id == REQUEST_ID
    assert KEY not in str(caught.value) and KEY not in repr(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [None, {}, {"choices": []}, {"smartroute": {"actual_cost_usd": None}}])
def test_malformed_chat_has_no_fabricated_cost(bad: object) -> None:
    """Incomplete routing data is a protocol failure, not a free response."""
    with SmartRoute(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=bad))) as client:
        with pytest.raises(SmartRouteError):
            client.chat("Hello")


@pytest.mark.parametrize(("field", "value"), [("actual_cost_usd", None), ("actual_cost_usd", -1), ("confidence", float("nan")), ("confidence", 2), ("escalated", "false"), ("tier_final", "unknown")])
def test_invalid_routing_values_are_rejected(field: str, value: object) -> None:
    """Do not coerce unknown costs, invalid confidence, or truthy string flags into success."""
    body = completion()
    body["smartroute"][field] = value
    with SmartRoute(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(body)))) as client:
        with pytest.raises(SmartRouteError):
            client.chat("Hello")


@pytest.mark.parametrize("url", ["http://public.example.test", "https://name:secret@example.test", "https://example.test?token=secret", "https://example.test#secret", "not-a-url"])
def test_unsafe_gateway_urls_rejected(url: str) -> None:
    """Reject credential-bearing URLs and remote cleartext before sending any request."""
    with pytest.raises(ValueError, match="HTTPS"):
        SmartRoute(url, KEY)


def test_transport_failure_is_redacted() -> None:
    """Timeouts cannot claim that a provider operation was never charged."""
    def handle(request: httpx.Request) -> httpx.Response:
        """Simulate a transport exception with unsafe diagnostic text."""
        raise httpx.ReadTimeout(KEY, request=request)
    with SmartRoute(api_key=KEY, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SmartRouteError, match="may have incurred charges") as caught:
            client.chat("Hello")
    assert KEY not in str(caught.value)


def test_environment_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use gateway environment variables and map boolean feedback to the existing API."""
    monkeypatch.setenv("SMARTROUTE_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("SMARTROUTE_API_KEY", KEY)
    def handle(request: httpx.Request) -> httpx.Response:
        """Verify source, key, and feedback payload."""
        assert request.url.path == "/v1/feedback"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert json.loads(request.content) == {"request_id": REQUEST_ID, "score": -1, "note": "Incomplete"}
        return httpx.Response(200, json={"request_id": REQUEST_ID, "score": -1, "note": "Incomplete"})
    with SmartRoute(transport=httpx.MockTransport(handle)) as client:
        assert client.feedback(REQUEST_ID, False, "Incomplete")["score"] == -1
        with pytest.raises(ValueError):
            client.feedback(REQUEST_ID, 1)


def test_provider_key_is_not_a_gateway_key() -> None:
    """Catch a common credential mix-up before sending it to the gateway."""
    with pytest.raises(ValueError, match="gateway key"):
        SmartRoute(api_key="sk-synthetic-provider-key")


def test_owner_setup_is_explicit() -> None:
    """Construction sends nothing; only explicit methods transmit provider configuration."""
    calls = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Verify that owner authorization is separate from a routine gateway key."""
        assert request.headers["authorization"] == "Bearer synthetic.owner.jwt"
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(204) if request.method == "DELETE" else httpx.Response(200, json={"id": "owned-credential"})
    with OwnerSetup("https://gateway.example.test", "synthetic.owner.jwt", transport=httpx.MockTransport(handle)) as setup:
        assert not calls
        setup.create_credential("openai", "Primary", "synthetic-provider-key")
        setup.configure_model("small", credential_id="owned-credential", model="test-model", input_price_per_1k=0, output_price_per_1k=0)
        setup.replace_credential("owned-credential", "synthetic-replacement-key")
        setup.delete_model("small")
        setup.delete_credential("owned-credential")
    assert calls[0][2]["api_key"] == "synthetic-provider-key"
    assert calls[1][2]["input_price_per_1k"] == 0 and calls[1][2]["self_check_max_tokens"] == 256
    assert calls[-1][:2] == ("DELETE", "/v1/credentials/owned-credential")
    with pytest.raises(ValueError, match="managed session"):
        OwnerSetup("https://gateway.example.test", KEY)
    assert not hasattr(SmartRoute, "configure_model")


@pytest.mark.parametrize("command", ["health", "models", "workspace", "stats", "requests", "request", "feedback", "chat", "bench"])
def test_cli_commands(command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Exercise console commands with deterministic HTTP responses and no real inference."""
    seen = []
    def handle(request: httpx.Request) -> httpx.Response:
        """Capture operation paths and provide a minimal command response."""
        seen.append(request.url.path)
        if command == "chat":
            return httpx.Response(200, json=completion())
        if command == "bench":
            assert json.loads(request.content)["limit"] == 2
            return httpx.Response(200, json={"prompt_count": 2, "summary": {"routing_accuracy": 0.5, "total_actual_usd": 0.01, "saved_pct": 10}})
        return httpx.Response(200, json={"status": "ok"})
    monkeypatch.setattr(cli, "SmartRoute", lambda **kwargs: SmartRoute(**kwargs, api_key=KEY, transport=httpx.MockTransport(handle)))
    arguments = [command]
    if command in {"request", "feedback"}:
        arguments.append(REQUEST_ID)
    if command == "feedback":
        arguments.append("--good")
    if command == "chat":
        arguments.append("Hello")
    if command == "bench":
        arguments += ["--limit", "2"]
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert output.out and not output.err and KEY not in output.out
    assert len(seen) == 1


def test_cli_failure_and_browser_setup(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Print only redacted failures and open setup without taking credentials on the CLI."""
    monkeypatch.setattr(cli, "SmartRoute", lambda **kwargs: SmartRoute(**kwargs, api_key=KEY, transport=httpx.MockTransport(lambda request: httpx.Response(401, text=KEY))))
    assert cli.main(["models"]) == 1
    assert KEY not in capsys.readouterr().err
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    assert cli.main(["setup", "--web-url", "http://localhost:5174"]) == 0
    assert opened == ["http://localhost:5174/models"]


def test_cli_malformed_benchmark_is_redacted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Malformed successful responses produce a concise error, not an exception traceback."""
    monkeypatch.setattr(cli, "SmartRoute", lambda **kwargs: SmartRoute(**kwargs, api_key=KEY, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": KEY}))))
    assert cli.main(["bench", "--limit", "1"]) == 1
    output = capsys.readouterr()
    assert "invalid command response" in output.err and KEY not in output.err and not output.out