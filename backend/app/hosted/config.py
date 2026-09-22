"""Load private hosted configuration and build redacted PostgreSQL connections."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr
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
    PROVIDER_ENCRYPTION_KEY: SecretStr = SecretStr("")


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