"""Load private hosted configuration and build redacted PostgreSQL connections."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class HostedSettings(BaseSettings):
    """Read hosted service configuration without exposing secrets in representations."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: SecretStr = SecretStr("")
    DATABASE_DIRECT_URL: SecretStr = SecretStr("")
    NEON_AUTH_BASE_URL: str = ""
    NEON_AUTH_ISSUER: str = ""
    NEON_AUTH_AUDIENCE: str = ""
    NEON_AUTH_ALGORITHM: Literal["EdDSA", "RS256", "ES256"] = "EdDSA"
    PROVIDER_ENCRYPTION_KEY: SecretStr = SecretStr("")
    PUBLIC_BASE_URL: str = ""
    RENDER_EXTERNAL_URL: str = ""
    HOSTED_RELEASE_APPROVED: bool = False
    REQUEST_MAX_BYTES: int = Field(default=524288, ge=4096, le=1048576)
    REQUEST_TIMEOUT_SECONDS: int = Field(default=180, ge=10, le=300)
    WORKSPACE_REQUESTS_PER_MINUTE: int = Field(default=120, ge=1, le=600)
    GLOBAL_REQUESTS_PER_MINUTE: int = Field(default=600, ge=10, le=3000)
    WORKSPACE_INFERENCES_PER_DAY: int = Field(default=100, ge=1, le=1000)
    WORKSPACE_HISTORY_LIMIT: int = Field(default=1000, ge=40, le=10000)
    REQUEST_RETENTION_DAYS: int = Field(default=30, ge=1, le=365)


def public_origin(configured: HostedSettings) -> str:
    """Require an approved HTTPS origin and explicit trusted JWT claims for public hosting."""
    if not configured.HOSTED_RELEASE_APPROVED:
        raise ValueError("Public startup is blocked until the deployment checklist is approved with HOSTED_RELEASE_APPROVED=true.")
    value = (configured.PUBLIC_BASE_URL or configured.RENDER_EXTERNAL_URL).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise ValueError("PUBLIC_BASE_URL must be the canonical HTTPS origin, without a path or credentials.")
    if not configured.NEON_AUTH_ISSUER or not configured.NEON_AUTH_AUDIENCE:
        raise ValueError("Public hosting requires explicit verified NEON_AUTH_ISSUER and NEON_AUTH_AUDIENCE.")
    try:
        Fernet(configured.PROVIDER_ENCRYPTION_KEY.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError):
        raise ValueError("Configure a valid server-only PROVIDER_ENCRYPTION_KEY.") from None
    if configured.DATABASE_DIRECT_URL.get_secret_value():
        raise ValueError("Remove DATABASE_DIRECT_URL from the public runtime; run migrations separately.")
    return value


def database_url(configured: HostedSettings, *, direct: bool = False) -> URL:
    """Validate a Neon TLS URL and select psycopg without echoing the connection string."""
    value = configured.DATABASE_DIRECT_URL if direct else configured.DATABASE_URL
    if not value.get_secret_value():
        raise ValueError("Configure DATABASE_DIRECT_URL." if direct else "Configure DATABASE_URL.")
    try:
        url = make_url(value.get_secret_value())
    except (ArgumentError, ValueError):
        raise ValueError("The database connection URL is invalid.") from None
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("Use a PostgreSQL connection URL.")
    if not url.host or not url.database or not url.username or not url.password:
        raise ValueError("The database URL must specify a host, database, role, and password.")
    if url.query.get("sslmode") not in ("require", "verify-ca", "verify-full"):
        raise ValueError("The database URL must require TLS.")
    if direct and "-pooler." in url.host:
        raise ValueError("Migrations require the direct URL, without -pooler in its hostname.")
    return url.set(drivername="postgresql+psycopg")


def auth_base_url(configured: HostedSettings) -> str:
    """Validate a credential-free HTTPS Auth Base URL without guessing its issuer."""
    value = configured.NEON_AUTH_BASE_URL.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use the public HTTPS Neon Auth Base URL without credentials or query parameters.")
    return value


def database_engine(configured: HostedSettings, *, direct: bool = False) -> Engine:
    """Create a small TLS connection pool with redacted SQL parameters."""
    return create_engine(
        database_url(configured, direct=direct),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_timeout=10,
        pool_recycle=300,
        hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )