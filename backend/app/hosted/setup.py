"""Safely verify Neon configuration and generate a server-only encryption key."""

import argparse
import json
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import set_key
from sqlalchemy import text

from app.hosted.config import HostedSettings, auth_base_url, database_engine, database_url


def configure_direct_url(configured: HostedSettings, env_path: Path) -> bool:
    """Derive a missing direct URL only from a standard Neon pooled hostname."""
    if configured.DATABASE_DIRECT_URL.get_secret_value():
        database_url(configured, direct=True)
        return False
    pooled = database_url(configured)
    if not pooled.host or not pooled.host.endswith((".neon.tech", ".neon.build")) or "-pooler." not in pooled.host:
        raise ValueError("Add DATABASE_DIRECT_URL manually for this database hostname.")
    direct = pooled.set(drivername="postgresql", host=pooled.host.replace("-pooler.", ".", 1))
    set_key(str(env_path), "DATABASE_DIRECT_URL", direct.render_as_string(hide_password=False))
    return True


def generate_encryption_key(configured: HostedSettings, env_path: Path) -> bool:
    """Write a new key only when none is configured, without printing its value."""
    existing = configured.PROVIDER_ENCRYPTION_KEY.get_secret_value()
    if existing:
        try:
            Fernet(existing.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("The existing encryption key is invalid; it was not replaced.") from None
        return False
    key = Fernet.generate_key().decode("ascii")
    set_key(str(env_path), "PROVIDER_ENCRYPTION_KEY", key)
    return True


def check_database(configured: HostedSettings) -> dict[str, bool]:
    """Verify both database URLs and Auth schema presence without modifying cloud data."""
    auth_base_url(configured)
    result: dict[str, bool] = {}
    for direct in (False, True):
        engine = database_engine(configured, direct=direct)
        try:
            with engine.connect() as connection:
                result["direct_connection" if direct else "pooled_connection"] = connection.execute(
                    text("SELECT 1")
                ).scalar_one() == 1
                if direct:
                    result["auth_schema_present"] = bool(connection.execute(
                        text("SELECT to_regnamespace('neon_auth') IS NOT NULL")
                    ).scalar_one())
        finally:
            engine.dispose()
    return result


def main(argv: list[str] | None = None) -> None:
    """Run secret-safe setup commands; never print connection strings or exception details."""
    parser = argparse.ArgumentParser(description="Configure the SmartRoute hosted foundation.")
    parser.add_argument("action", choices=["check", "generate-key", "derive-direct-url"])
    args = parser.parse_args(argv)
    try:
        configured = HostedSettings()
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if args.action == "generate-key":
            created = generate_encryption_key(configured, env_path)
            print(json.dumps({"encryption_key_ready": True, "generated": created}))
        elif args.action == "derive-direct-url":
            created = configure_direct_url(configured, env_path)
            print(json.dumps({"direct_url_ready": True, "generated": created}))
        else:
            result = check_database(configured)
            print(json.dumps(result))
            if not all(result.values()):
                raise SystemExit("Enable Neon Auth on the selected database branch before proceeding.")
    except Exception as error:
        raise SystemExit(
            f"Hosted setup failed ({type(error).__name__}). Check local configuration and connectivity; secret values were not displayed."
        ) from None


if __name__ == "__main__":
    main()