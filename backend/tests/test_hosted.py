"""Verify the hosted foundation without using real Neon credentials or accounts."""

from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import IntegrityError

from app import main
from app.hosted.config import HostedSettings, auth_base_url, database_engine, database_url
from app.hosted import schema
from app.hosted.secrets import decrypt_provider_key, encrypt_provider_key, new_api_key, verify_api_key
from app.hosted.setup import configure_direct_url, generate_encryption_key


@pytest.fixture
def hosted_settings(monkeypatch: pytest.MonkeyPatch) -> HostedSettings:
    """Keep hosted tests independent of local and process-level secret values."""
    for name in HostedSettings.model_fields:
        monkeypatch.delenv(name, raising=False)
    return HostedSettings(
        _env_file=None,
        DATABASE_URL="postgresql://test_role:test-only-password@ep-test-pooler.example.test/testdb?sslmode=require",
        DATABASE_DIRECT_URL="postgresql://test_role:test-only-password@ep-test.example.test/testdb?sslmode=require",
        NEON_AUTH_BASE_URL="https://ep-test.neonauth.example.test/testdb/auth",
    )


def test_hosted_urls_and_redaction(hosted_settings: HostedSettings) -> None:
    """Normalize the driver while keeping credentials out of settings and URL representations."""
    pooled = database_url(hosted_settings)
    direct = database_url(hosted_settings, direct=True)

    assert pooled.drivername == direct.drivername == "postgresql+psycopg"
    assert pooled.query["sslmode"] == "require"
    assert "-pooler." in pooled.host and "-pooler." not in direct.host
    assert "test-only-password" not in repr(hosted_settings)
    assert "test-only-password" not in str(pooled)
    assert auth_base_url(hosted_settings).endswith("/auth")


@pytest.mark.parametrize("value", [
    "", "invalid-secret-string", "sqlite:///local.db",
    "postgresql://role:secret@db.example.test/db",
    "postgresql://role:secret@db.example.test/db?sslmode=disable",
    "postgresql://role@db.example.test/db?sslmode=require",
])
def test_invalid_database_urls_are_safe(hosted_settings: HostedSettings, value: str) -> None:
    """Reject missing or non-TLS credentials without including their value in an error."""
    hosted_settings.DATABASE_URL = SecretStr(value)

    with pytest.raises(ValueError) as caught:
        database_url(hosted_settings)

    assert "secret" not in str(caught.value)


def test_migrations_reject_pooled_url(hosted_settings: HostedSettings) -> None:
    """DDL must not accidentally use the transaction-pooling endpoint."""
    hosted_settings.DATABASE_DIRECT_URL = hosted_settings.DATABASE_URL
    with pytest.raises(ValueError, match="direct URL"):
        database_url(hosted_settings, direct=True)


@pytest.mark.parametrize("value", ["", "http://auth.example.test", "https://user:secret@auth.example.test", "https://auth.example.test?token=secret"])
def test_auth_url_has_no_credentials(hosted_settings: HostedSettings, value: str) -> None:
    """Treat the browser-visible auth URL as public configuration, never a secret container."""
    hosted_settings.NEON_AUTH_BASE_URL = value
    with pytest.raises(ValueError):
        auth_base_url(hosted_settings)


def test_engine_creation_does_not_connect(hosted_settings: HostedSettings) -> None:
    """Construct a bounded pool without making a network connection during import or setup."""
    engine = database_engine(hosted_settings)
    try:
        assert engine.hide_parameters is True
        assert engine.pool.size() == 2
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_key_generation_preserves_configuration(
    hosted_settings: HostedSettings, tmp_path: Path
) -> None:
    """Generate directly into an environment file and never rotate a valid existing key."""
    path = tmp_path / ".env"
    path.write_text("EXISTING_VALUE=preserved\n", encoding="utf-8")

    assert generate_encryption_key(hosted_settings, path) is True
    values = dotenv_values(path)
    assert values["EXISTING_VALUE"] == "preserved"
    key = values["PROVIDER_ENCRYPTION_KEY"]
    assert key is not None
    Fernet(key.encode("ascii"))
    hosted_settings.PROVIDER_ENCRYPTION_KEY = SecretStr(key)
    assert generate_encryption_key(hosted_settings, path) is False
    assert dotenv_values(path)["PROVIDER_ENCRYPTION_KEY"] == key


def test_derive_direct_neon_url(hosted_settings: HostedSettings, tmp_path: Path) -> None:
    """Derive the standard non-pooled hostname without changing credentials or TLS options."""
    path = tmp_path / ".env"
    hosted_settings.DATABASE_URL = SecretStr(
        "postgresql://test_role:test-only-password@ep-test-pooler.us-east-2.aws.neon.tech/testdb?sslmode=require"
    )
    hosted_settings.DATABASE_DIRECT_URL = SecretStr("")

    assert configure_direct_url(hosted_settings, path) is True
    value = dotenv_values(path)["DATABASE_DIRECT_URL"]
    assert value is not None
    hosted_settings.DATABASE_DIRECT_URL = SecretStr(value)
    direct = database_url(hosted_settings, direct=True)
    assert direct.host == "ep-test.us-east-2.aws.neon.tech"
    assert direct.password == "test-only-password"
    assert configure_direct_url(hosted_settings, path) is False


def test_api_key_hashing() -> None:
    """Store only a hash and short prefix of a randomly generated workspace key."""
    token, digest, prefix = new_api_key()
    other, _, _ = new_api_key()
    assert token.startswith("sr_") and len(token) >= 43
    assert len(digest) == 64 and token not in digest
    assert len(prefix) == 11 and token.startswith(prefix)
    assert verify_api_key(token, digest)
    assert not verify_api_key(other, digest)


def test_provider_encryption_is_workspace_bound(hosted_settings: HostedSettings) -> None:
    """Encrypted credentials cannot be substituted across tenants or provider types."""
    hosted_settings.PROVIDER_ENCRYPTION_KEY = SecretStr(Fernet.generate_key().decode("ascii"))
    workspace_id = uuid4()
    encrypted = encrypt_provider_key(hosted_settings, workspace_id, "openai", "test-only-provider-key")
    assert b"test-only-provider-key" not in encrypted
    assert decrypt_provider_key(hosted_settings, workspace_id, "openai", encrypted) == "test-only-provider-key"
    for owner, provider in [(uuid4(), "openai"), (workspace_id, "anthropic")]:
        with pytest.raises(ValueError, match="could not be decrypted"):
            decrypt_provider_key(hosted_settings, owner, provider, encrypted)
    with pytest.raises(ValueError):
        decrypt_provider_key(hosted_settings, workspace_id, "openai", b"invalid")


def test_schema_tenant_constraints() -> None:
    """A model cannot reference another workspace's stored credential."""
    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {schema.SCHEMA: None}})
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            schema.metadata.create_all(connection)
            owner_id, other_owner_id, workspace_id, other_workspace_id, credential_id = [uuid4() for _ in range(5)]
            for user_id, subject in [(owner_id, "subject-one"), (other_owner_id, "subject-two")]:
                connection.execute(insert(schema.users).values(
                    id=user_id, auth_issuer="https://auth.example.test", auth_subject=subject,
                    email=f"{subject}@example.test", display_name=subject,
                ))
            connection.execute(insert(schema.workspaces), [
                {"id": workspace_id, "owner_id": owner_id, "name": "First"},
                {"id": other_workspace_id, "owner_id": other_owner_id, "name": "Second"},
            ])
            connection.execute(insert(schema.provider_credentials).values(
                id=credential_id, workspace_id=workspace_id, provider="openai", label="Primary",
                ciphertext=b"encrypted-test-data", key_suffix="1234",
            ))
            values = {
                "credential_id": credential_id, "tier": "small", "model": "test-model",
                "input_price_per_1k": 0, "output_price_per_1k": 0,
            }
            connection.execute(insert(schema.models).values(workspace_id=workspace_id, **values))
            with pytest.raises(IntegrityError):
                connection.execute(insert(schema.models).values(workspace_id=other_workspace_id, **values))
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_hosted_startup_is_blocked_until_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not advertise an authenticated deployment while legacy global routes remain active."""
    monkeypatch.setattr(main.settings, "APP_MODE", "hosted")
    with pytest.raises(RuntimeError, match="workspace-scoped routes"):
        async with main.app.router.lifespan_context(main.app):
            pass