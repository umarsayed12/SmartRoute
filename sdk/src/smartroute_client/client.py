"""Call a SmartRoute gateway without storing provider keys or retrying billable work."""

import ipaddress
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx


class SmartRouteError(RuntimeError):
    """Expose safe diagnostics without retaining the request, credentials, or response body."""

    def __init__(self, message: str, *, status_code: int | None = None, request_id: str | None = None) -> None:
        """Keep only status and an optional gateway audit identifier."""
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


@dataclass(frozen=True)
class ChatResult:
    """Describe the final answer and cumulative routing cost, including auxiliary calls."""

    content: str
    tier: str
    escalated: bool
    confidence: float
    cost_usd: float
    saved_usd: float
    request_id: str
    raw: dict[str, Any] = field(repr=False)


def _base_url(value: str) -> httpx.URL:
    """Require HTTPS except for loopback development, and accept roots with or without /v1."""
    try:
        url = httpx.URL(value)
        loopback = url.host == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(url.host).is_loopback
            except ValueError:
                pass
        if not url.host or url.userinfo or url.query or url.fragment or (url.scheme != "https" and not (url.scheme == "http" and loopback)):
            raise ValueError
        path = url.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        return url.copy_with(path=path + "/")
    except (ValueError, httpx.InvalidURL):
        raise ValueError("Use an HTTPS gateway URL without credentials, query, or fragment; HTTP is loopback-only.") from None


def _client(base_url: str | None, token: str | None, source: str, timeout: float, transport: httpx.BaseTransport | None) -> httpx.Client:
    """Build a redirect-free transport with explicit source attribution and no retries."""
    if source not in {"api", "playground", "testlab", "sdk"}:
        raise ValueError("Invalid SmartRoute source.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a positive finite number.")
    headers = {"X-SmartRoute-Source": source, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=_base_url(base_url or os.getenv("SMARTROUTE_BASE_URL") or "http://localhost:8000"),
                        headers=headers, timeout=timeout, follow_redirects=False, transport=transport)


def _response(response: httpx.Response) -> Any:
    """Decode successful JSON and discard potentially secret-bearing error bodies."""
    if not 200 <= response.status_code < 300:
        request_id = None
        try:
            body = response.json()
            candidate = body.get("request_id") if isinstance(body, dict) else None
            if isinstance(candidate, str) and re.fullmatch(r"chatcmpl-[0-9a-f]{32}", candidate):
                request_id = candidate
        except ValueError:
            pass
        messages = {401: "Authentication failed. Check your SmartRoute gateway key.",
                    403: "This credential is not authorized for the operation.",
                    409: "Workspace setup is incomplete or conflicts with this operation.",
                    429: "Workspace capacity is busy. Check history before retrying."}
        message = messages.get(response.status_code, "Gateway request failed. Check request history before retrying.")
        raise SmartRouteError(f"{message} (HTTP {response.status_code})", status_code=response.status_code, request_id=request_id)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise SmartRouteError("Gateway returned invalid JSON.") from None


def _number(value: Any) -> float:
    """Reject missing, negative, boolean, or non-finite cost/confidence values."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError
    return float(value)


def _chat_result(data: Any) -> ChatResult:
    """Require actual routing metadata instead of inventing costs or confidence defaults."""
    try:
        routing = data["smartroute"]
        content = data["choices"][0]["message"]["content"]
        cost, reference, confidence = (_number(routing[key]) for key in ("actual_cost_usd", "reference_cost_usd", "confidence"))
        if not isinstance(content, str) or not content.strip() or routing["tier_final"] not in ("small", "medium", "large") or type(routing["escalated"]) is not bool or confidence > 1:
            raise ValueError
        if not isinstance(data["id"], str) or not data["id"] or routing["request_id"] != data["id"]:
            raise ValueError
        return ChatResult(content, routing["tier_final"], routing["escalated"], confidence, cost, reference - cost, data["id"], data)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise SmartRouteError("Gateway returned an invalid chat response or routing metadata.") from None


class SmartRoute:
    """Use a workspace gateway key; construction never changes saved provider configuration."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, source: str = "sdk", *, timeout: float = 300, transport: httpx.BaseTransport | None = None) -> None:
        """Read optional SMARTROUTE_BASE_URL/SMARTROUTE_API_KEY defaults; transport supports offline tests."""
        token = api_key if api_key is not None else os.getenv("SMARTROUTE_API_KEY")
        if token and not re.fullmatch(r"sr_[A-Za-z0-9_-]{43}", token):
            raise ValueError("Use a SmartRoute gateway key, not a provider key or owner session token.")
        self._client = _client(base_url, token, source, timeout, transport)

    def __enter__(self) -> "SmartRoute":
        """Support deterministic connection cleanup with a context manager."""
        return self

    def __exit__(self, *_args: Any) -> None:
        """Release pooled connections on context exit."""
        self.close()

    def close(self) -> None:
        """Release the client's HTTP connection pool."""
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Translate transport failures without exposing raw request data or retrying."""
        try:
            return _response(self._client.request(method, path, **kwargs))
        except httpx.HTTPError:
            raise SmartRouteError("Gateway connection failed or timed out. The request may have incurred charges; check history before retrying.") from None

    def chat(self, messages: str | list[dict[str, str]], model: str = "smartroute/auto", **options: Any) -> ChatResult:
        """Generate a text answer using saved workspace models and return routing metadata."""
        if options.get("stream"):
            raise ValueError("Streaming is not supported by this client.")
        conversation = [{"role": "user", "content": messages}] if isinstance(messages, str) else messages
        return _chat_result(self._request("POST", "v1/chat/completions", json={"messages": conversation, "model": model, **options}))

    def feedback(self, request_id: str, good: bool, note: str | None = None) -> dict[str, Any]:
        """Rate one owned completed request; repeated ratings replace the prior rating."""
        if type(good) is not bool:
            raise ValueError("good must be a boolean.")
        return self._request("POST", "v1/feedback", json={"request_id": request_id, "score": 1 if good else -1, "note": note})

    def stats(self, days: int = 7) -> dict[str, Any]:
        """Read completed-request statistics, not total provider invoice spend."""
        return self._request("GET", "v1/stats", params={"days": days})

    def health(self) -> dict[str, Any]:
        """Read gateway readiness without making a model generation call."""
        return self._request("GET", "health")

    def workspace(self) -> dict[str, Any]:
        """Read the workspace resolved from this credential."""
        return self._request("GET", "v1/me")

    def models(self) -> list[dict[str, Any]]:
        """List owned tier metadata without provider credentials or generation calls."""
        return self._request("GET", "v1/models")

    def requests(self, **filters: Any) -> dict[str, Any]:
        """List private request summaries using the gateway's pagination and filters."""
        return self._request("GET", "v1/requests", params=filters)

    def request(self, request_id: str) -> dict[str, Any]:
        """Inspect one private request and every recorded provider attempt."""
        return self._request("GET", f"v1/requests/{quote(request_id, safe='')}")

    def bench(self, mode: str = "auto", limit: int = 5) -> dict[str, Any]:
        """Explicitly execute a bounded Test Lab suite; this can incur provider charges."""
        if mode not in {"auto", "small", "medium", "large"} or type(limit) is not int or not 1 <= limit <= 40:
            raise ValueError("Bench requires a routing mode and a limit from 1 to 40.")
        return self._request("POST", "v1/testlab/run", json={"suite": "default", "mode": mode, "limit": limit})