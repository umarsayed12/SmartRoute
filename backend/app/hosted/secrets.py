"""Hash high-entropy gateway keys and encrypt provider credentials with tenant context."""

import hashlib
import hmac
import json
import secrets
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.hosted.config import HostedSettings


def new_api_key() -> tuple[str, str, str]:
    """Return a one-time plaintext key, its hash, and a non-secret display prefix."""
    token = f"sr_{secrets.token_urlsafe(32)}"
    return token, hash_api_key(token), token[:11]


def hash_api_key(token: str) -> str:
    """Hash a machine-generated high-entropy key for lookup without persisting plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_api_key(token: str, expected_hash: str) -> bool:
    """Compare a presented API key's hash in constant time."""
    return hmac.compare_digest(hash_api_key(token), expected_hash)


def _cipher(configured: HostedSettings) -> Fernet:
    """Construct the credential cipher without exposing invalid configured key material."""
    try:
        return Fernet(configured.PROVIDER_ENCRYPTION_KEY.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError):
        raise ValueError("Configure a valid PROVIDER_ENCRYPTION_KEY.") from None


def encrypt_provider_key(
    configured: HostedSettings, workspace_id: UUID, provider: str, api_key: str
) -> bytes:
    """Encrypt a provider key together with its owning workspace and provider identity."""
    if provider not in ("openai", "anthropic") or not api_key.strip():
        raise ValueError("A supported provider and nonempty key are required.")
    payload = json.dumps({"workspace_id": str(workspace_id), "provider": provider, "api_key": api_key})
    return _cipher(configured).encrypt(payload.encode("utf-8"))


def decrypt_provider_key(
    configured: HostedSettings, workspace_id: UUID, provider: str, ciphertext: bytes
) -> str:
    """Reject corrupted credentials and ciphertext copied from another workspace/provider."""
    try:
        payload = json.loads(_cipher(configured).decrypt(ciphertext))
        if payload["workspace_id"] != str(workspace_id) or payload["provider"] != provider:
            raise ValueError("Credential context does not match.")
        value = payload["api_key"]
        if not isinstance(value, str) or not value:
            raise ValueError("Invalid credential payload.")
        return value
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise ValueError("Provider credential could not be decrypted for this workspace.") from None