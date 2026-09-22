"""Keep explicit provider administration separate from ordinary gateway-key use."""

from typing import Any
from urllib.parse import quote

import httpx

from smartroute_client.client import SmartRoute, _client


class OwnerSetup(SmartRoute):
    """Administer saved models using an explicitly supplied, short-lived managed owner JWT."""

    def __init__(self, base_url: str, session_token: str, *, timeout: float = 30, transport: httpx.BaseTransport | None = None) -> None:
        """Never acquire a browser session or promote an ordinary gateway key implicitly."""
        if not session_token or session_token.count(".") != 2 or any(ord(character) < 33 or ord(character) > 126 for character in session_token) or session_token.startswith(("sr_", "sk-")):
            raise ValueError("Owner setup requires an explicit managed session JWT, not a gateway/provider key.")
        self._client = _client(base_url, session_token, "sdk", timeout, transport)

    def credentials(self) -> list[dict[str, Any]]:
        """List owned credential metadata, never previously saved key values."""
        return self._request("GET", "v1/credentials")

    def create_credential(self, provider: str, label: str, api_key: str) -> dict[str, Any]:
        """Explicitly send a provider key for encrypted storage; the gateway enforces ownership."""
        return self._request("POST", "v1/credentials", json={"provider": provider, "label": label, "api_key": api_key})

    def replace_credential(self, credential_id: str, api_key: str) -> dict[str, Any]:
        """Replace an owned provider key without changing tier mappings."""
        return self._request("PUT", f"v1/credentials/{quote(credential_id, safe='')}", json={"api_key": api_key})

    def delete_credential(self, credential_id: str) -> None:
        """Delete an owned credential and its model mappings, preserving historical requests."""
        self._request("DELETE", f"v1/credentials/{quote(credential_id, safe='')}")

    def configure_model(self, tier: str, *, credential_id: str, model: str, input_price_per_1k: float, output_price_per_1k: float, enabled: bool = True, send_temperature: bool = True, self_check_max_tokens: int = 256) -> dict[str, Any]:
        """Explicitly save one tier with owned credentials and caller-supplied standard prices."""
        if tier not in {"small", "medium", "large"}:
            raise ValueError("Invalid model tier.")
        return self._request("PUT", f"v1/models/{tier}", json={"credential_id": credential_id, "model": model,
            "input_price_per_1k": input_price_per_1k, "output_price_per_1k": output_price_per_1k,
            "enabled": enabled, "send_temperature": send_temperature, "self_check_max_tokens": self_check_max_tokens})

    def delete_model(self, tier: str) -> None:
        """Remove one tier, not the provider key or historical request records."""
        if tier not in {"small", "medium", "large"}:
            raise ValueError("Invalid model tier.")
        self._request("DELETE", f"v1/models/{tier}")