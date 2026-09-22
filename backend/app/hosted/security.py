"""Bound public HTTP resource use and apply same-origin browser security headers."""

import asyncio
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.hosted.config import HostedSettings


class WindowLimiter:
    """Use bounded per-process minute windows; deployment must use one worker/instance."""

    def __init__(self, limit: int, capacity: int = 2048) -> None:
        """Bound both request counts and in-memory identity cardinality."""
        self.limit, self.capacity = limit, capacity
        self.entries: dict[str, tuple[int, int]] = {}
        self.lock = Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Expire old windows and deny admission when the counter or map is full."""
        window = int((monotonic() if now is None else now) // 60)
        with self.lock:
            self.entries = {identity: value for identity, value in self.entries.items() if value[0] == window}
            current = self.entries.get(key)
            if current is None and len(self.entries) >= self.capacity:
                return False
            count = current[1] if current else 0
            if count >= self.limit:
                return False
            self.entries[key] = (window, count + 1)
            return True


class PublicBoundary:
    """Reject oversized or cross-origin API traffic before parsing and constrain total request time."""

    def __init__(self, app: ASGIApp, configured: HostedSettings, origin: str) -> None:
        """Set explicit public limits without trusting client forwarding headers."""
        self.app, self.configured, self.origin = app, configured, origin
        auth = urlsplit(configured.NEON_AUTH_BASE_URL)
        self.auth_origin = f"{auth.scheme}://{auth.netloc}"
        self.global_limiter = WindowLimiter(configured.GLOBAL_REQUESTS_PER_MINUTE, capacity=1)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve bounded requests and preserve structured errors instead of leaking exceptions."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        started = False
        async def secured_send(message: Message) -> None:
            """Apply headers even to validation and capacity failures."""
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                outgoing = MutableHeaders(scope=message)
                outgoing["X-Content-Type-Options"] = "nosniff"
                outgoing["X-Frame-Options"] = "DENY"
                outgoing["Referrer-Policy"] = "no-referrer"
                outgoing["Strict-Transport-Security"] = "max-age=31536000"
                outgoing["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                outgoing["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' {self.auth_origin}; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
                if scope["path"].startswith("/v1") or scope["path"] == "/health" or message["status"] >= 400:
                    outgoing["Cache-Control"] = "no-store"
            await send(message)

        async def reject(status: int, detail: str) -> None:
            """Respond without reflecting the submitted URL, token, or body."""
            response = JSONResponse(status_code=status, content={"detail": detail}, headers={"Retry-After": "60"} if status == 429 else None)
            await response(scope, receive, secured_send)

        async def dispatch() -> None:
            """Buffer at most the configured JSON request size before handing it to the app."""
            if headers.get("origin") and headers["origin"] != self.origin:
                await reject(403, "This browser origin is not allowed.")
                return
            if len(headers.get("authorization", "")) > 8192:
                await reject(431, "Authorization header is too large.")
                return
            if scope["path"].startswith("/v1") and not self.global_limiter.allow("api"):
                await reject(429, "Gateway request capacity is busy.")
                return
            if headers.get("content-encoding", "identity") != "identity":
                await reject(415, "Encoded request bodies are unsupported.")
                return
            try:
                size = int(headers.get("content-length", "0"))
                if size < 0:
                    raise ValueError
            except ValueError:
                await reject(400, "Invalid request length.")
                return
            if size > self.configured.REQUEST_MAX_BYTES:
                await reject(413, "Request body is too large.")
                return
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > self.configured.REQUEST_MAX_BYTES:
                    await reject(413, "Request body is too large.")
                    return
                if not event.get("more_body", False):
                    break
            consumed = False
            async def buffered_receive() -> Message:
                """Replay the bounded body once and preserve disconnect notifications."""
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
            await self.app(scope, buffered_receive, secured_send)

        try:
            await asyncio.wait_for(dispatch(), timeout=self.configured.REQUEST_TIMEOUT_SECONDS)
        except TimeoutError:
            if not started:
                await reject(504, "Gateway request deadline exceeded. Check history before retrying.")