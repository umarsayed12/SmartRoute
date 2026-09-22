"""Verify Neon access JWTs against fixed trusted signing keys and strict claims."""

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic

import httpx
import jwt

from app.hosted.config import HostedSettings, auth_base_url

_logger = logging.getLogger(__name__)

class InvalidIdentityError(ValueError):
    """Indicate an invalid, expired, or untrusted bearer token without exposing it."""


class IdentityServiceUnavailableError(RuntimeError):
    """Indicate that trusted signing keys could not be obtained."""


@dataclass(frozen=True)
class Identity:
    """Carry only verified identity fields needed to provision a private workspace."""

    issuer: str
    subject: str
    email: str
    display_name: str
    email_verified: bool


class NeonTokenVerifier:
    """Cache trusted JWKS keys briefly and never follow token-supplied key URLs."""

    def __init__(self, configured: HostedSettings, client: httpx.AsyncClient) -> None:
        """Bind verification to deployment configuration and an async HTTP client."""
        base = auth_base_url(configured)
        self.issuer = configured.NEON_AUTH_ISSUER or base
        self.audience = configured.NEON_AUTH_AUDIENCE or base
        self.algorithm = configured.NEON_AUTH_ALGORITHM
        self.jwks_url = f"{base}/.well-known/jwks.json"
        self.client = client
        self.keys: dict[str, jwt.PyJWK] = {}
        self.refreshed_at = float("-inf")
        self.refresh_lock = asyncio.Lock()

    async def _key(self, key_id: str) -> jwt.PyJWK:
        """Refresh stale keys or an unknown key ID, with a short refresh-rate bound."""
        async with self.refresh_lock:
            age = monotonic() - self.refreshed_at
            if age >= 300 or (key_id not in self.keys and age >= 5):
                self.refreshed_at = monotonic()
                try:
                    response = await self.client.get(self.jwks_url, follow_redirects=False)
                    response.raise_for_status()
                    document = response.json()
                    key_rows = document.get("keys", [])
                    if not isinstance(key_rows, list) or not 1 <= len(key_rows) <= 32:
                        raise ValueError("Invalid key set.")
                    keys = {}
                    for row in key_rows:
                        if isinstance(row, dict) and isinstance(row.get("kid"), str) and row.get("alg", self.algorithm) == self.algorithm and row.get("use", "sig") == "sig":
                            keys[row["kid"]] = jwt.PyJWK.from_dict(row, algorithm=self.algorithm)
                    if not keys:
                        raise ValueError("No supported signing keys.")
                    self.keys = keys
                except (httpx.HTTPError, ValueError, TypeError, AttributeError, jwt.PyJWTError):
                    self.keys = {}
                    raise IdentityServiceUnavailableError("Authentication service is unavailable.") from None
            key = self.keys.get(key_id)
            if key is None:
                raise InvalidIdentityError("Invalid or expired authentication token.")
            return key

    async def verify(self, token: str) -> Identity:
        """Require signature, algorithm, issuer, audience, subject, issued time, and expiry."""
        try:
            if not token or len(token) > 16384:
                raise ValueError("Invalid token length.")
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            if header.get("alg") != self.algorithm or not isinstance(key_id, str) or not 1 <= len(key_id) <= 256:
                raise ValueError("Invalid token header.")
            key = await self._key(key_id)
            claims = jwt.decode(
                token, key.key, algorithms=[self.algorithm], issuer=self.issuer,
                audience=self.audience, leeway=5,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = claims["sub"]
            email = claims.get("email")
            name = claims.get("name", "")
            if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
                raise ValueError("Invalid subject.")
            if not isinstance(email, str) or "@" not in email or len(email) > 320:
                raise ValueError("Missing identity email.")
            return Identity(
                issuer=self.issuer, subject=subject, email=email,
                display_name=(name if isinstance(name, str) and name else email.split("@")[0])[:160],
                email_verified=claims.get("email_verified", claims.get("emailVerified")) is True,
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
            _logger.warning("Neon access token rejected (%s).", type(error).__name__)
            raise InvalidIdentityError("Invalid or expired authentication token.") from None