"""Validate workspace-owned provider credentials and logical model-tier configuration."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ProviderName = Literal["openai", "anthropic"]
TierName = Literal["small", "medium", "large"]


class CredentialCreate(BaseModel):
    """Accept a supported provider and secret without allowing caller-controlled URLs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: ProviderName
    label: str = Field(min_length=1, max_length=80)
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        """Reject empty, oversized, or header-breaking credentials without echoing them."""
        key = value.get_secret_value()
        if not 8 <= len(key) <= 4096 or key != key.strip() or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ValueError("Invalid provider credential.")
        return value


class CredentialReplace(BaseModel):
    """Rotate only a secret; provider identity and workspace ownership cannot change."""

    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        """Apply the same secret validation as credential creation."""
        return CredentialCreate.validate_key(value)


class ModelConfiguration(BaseModel):
    """Map one workspace tier to an owned credential and explicit standard token prices."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    credential_id: UUID
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    input_price_per_1k: Decimal = Field(ge=0, max_digits=20, decimal_places=10, allow_inf_nan=False)
    output_price_per_1k: Decimal = Field(ge=0, max_digits=20, decimal_places=10, allow_inf_nan=False)
    enabled: bool = Field(default=True, strict=True)
    send_temperature: bool = Field(default=True, strict=True)
    self_check_max_tokens: int = Field(default=256, ge=32, le=1024, strict=True)