"""Verify strict token claims, trusted JWKS usage, expiry, and key-refresh behavior."""

import json
from time import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.hosted.config import HostedSettings
from app.hosted.identity import IdentityServiceUnavailableError, InvalidIdentityError, NeonTokenVerifier


@pytest.fixture
def signing() -> tuple[Ed25519PrivateKey, dict[str, object]]:
    """Create an ephemeral signing key that is never associated with a real user."""
    private = Ed25519PrivateKey.generate()
    public = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(private.public_key()))
    return private, {**public, "kid": "test-key", "alg": "EdDSA", "use": "sig"}


def _token(private: Ed25519PrivateKey, **updates: object) -> str:
    """Sign representative claims with explicit issuer and audience for an external API."""
    now = int(time())
    return jwt.encode({
        "iss": "https://auth.example.test/db/auth", "aud": "https://auth.example.test/db/auth",
        "sub": "user-one", "email": "one@example.test", "name": "One",
        "emailVerified": True, "iat": now, "exp": now + 60, **updates,
    }, private, algorithm="EdDSA", headers={"kid": "test-key"})


@pytest.mark.asyncio
async def test_verified_identity_and_cached_keys(signing: tuple) -> None:
    """Read claims only after validation and reuse trusted keys for subsequent tokens."""
    private, public = signing
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Accept only the configured public key endpoint."""
        requests.append(str(request.url))
        return httpx.Response(200, json={"keys": [public]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        verifier = NeonTokenVerifier(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), client)
        first = await verifier.verify(_token(private))
        second = await verifier.verify(_token(private, sub="user-two", email="two@example.test"))

    assert first.subject == "user-one" and first.email_verified is True
    assert second.subject == "user-two"
    assert requests == ["https://auth.example.test/db/auth/.well-known/jwks.json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"iss": "https://other.example.test"}, {"aud": "other-service"},
    {"exp": 1}, {"iat": 9999999999}, {"sub": ""}, {"email": "invalid"},
])
async def test_untrusted_claims_are_rejected(signing: tuple, updates: dict[str, object]) -> None:
    """Reject forged identity context even when the signature uses the configured test key."""
    private, public = signing
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [public]}))) as client:
        verifier = NeonTokenVerifier(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), client)
        with pytest.raises(InvalidIdentityError):
            await verifier.verify(_token(private, **updates))


@pytest.mark.asyncio
async def test_unknown_key_refresh_and_wrong_signature(signing: tuple) -> None:
    """Accept a rotated trusted key only after refreshing and reject a different signing key."""
    private, public = signing
    current = {"keys": [public]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=current))) as client:
        verifier = NeonTokenVerifier(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), client)
        await verifier.verify(_token(private))
        other = Ed25519PrivateKey.generate()
        with pytest.raises(InvalidIdentityError):
            await verifier.verify(_token(other))
        current["keys"] = [{**json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(other.public_key())), "kid": "rotated", "alg": "EdDSA"}]
        verifier.refreshed_at -= 6
        claims = jwt.decode(_token(other), options={"verify_signature": False})
        rotated = jwt.encode(claims, other, algorithm="EdDSA", headers={"kid": "rotated"})
        assert (await verifier.verify(rotated)).subject == "user-one"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "not-a-jwt", "x" * 16385])
async def test_invalid_tokens_do_not_fetch_keys(token: str) -> None:
    """Reject malformed input without performing unnecessary auth-service requests."""
    def handle(request: httpx.Request) -> httpx.Response:
        """Fail if malformed input causes outbound traffic."""
        raise AssertionError("Unexpected network request.")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        verifier = NeonTokenVerifier(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), client)
        with pytest.raises(InvalidIdentityError):
            await verifier.verify(token)


@pytest.mark.asyncio
async def test_key_service_failure_is_not_an_identity(signing: tuple) -> None:
    """A key-service failure is controlled and never accepts unverified claims."""
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        verifier = NeonTokenVerifier(HostedSettings(_env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth"), client)
        with pytest.raises(IdentityServiceUnavailableError):
            await verifier.verify(_token(signing[0]))


@pytest.mark.asyncio
async def test_explicit_origin_claims(signing: tuple) -> None:
    """Support the confirmed managed-service origin while rejecting a path-based issuer."""
    private, public = signing
    configured = HostedSettings(
        _env_file=None, NEON_AUTH_BASE_URL="https://auth.example.test/db/auth",
        NEON_AUTH_ISSUER="https://auth.example.test", NEON_AUTH_AUDIENCE="https://auth.example.test",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": [public]}))) as client:
        verifier = NeonTokenVerifier(configured, client)
        identity = await verifier.verify(_token(private, iss="https://auth.example.test", aud="https://auth.example.test"))
        assert identity.subject == "user-one"
        with pytest.raises(InvalidIdentityError):
            await verifier.verify(_token(private))