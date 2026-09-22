"""Verify actual PostgreSQL RLS in an explicitly disposable CI database, never the configured Neon database."""

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.hosted import schema
from app.hosted.access import scope_workspace, validate_runtime_database
from app.hosted.identity import Identity
from app.hosted.store import WorkspaceStore


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="Disposable PostgreSQL is provided by CI, not the local Neon environment.")
def test_real_postgres_tenant_policies() -> None:
    """Prove unscoped denial, cross-tenant read/write denial, and context cleanup after pool reuse."""
    url = make_url(os.environ["TEST_POSTGRES_URL"])
    if url.database != "smartroute_ci" or url.host not in {"localhost", "127.0.0.1"}:
        pytest.fail("The policy test only permits the disposable loopback smartroute_ci database.")
    owner = create_engine(url, hide_parameters=True)
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("tenant_policy_migration", root / "migrations/versions/0003_tenant_policies.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    created = False
    try:
        with owner.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA smartroute")
            connection.exec_driver_sql("CREATE SCHEMA neon_auth")
            connection.exec_driver_sql('CREATE TABLE neon_auth."user" (id text PRIMARY KEY, email text, name text, "emailVerified" boolean)')
            schema.metadata.create_all(connection)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.exec_driver_sql((root / "scripts/runtime_role.sql").read_text(encoding="utf-8"))
            connection.exec_driver_sql("ALTER ROLE smartroute_runtime PASSWORD 'ci-only-runtime-password'")
        created = True
        runtime = create_engine(url.set(username="smartroute_runtime", password="ci-only-runtime-password"), pool_size=1, max_overflow=0, hide_parameters=True)
        try:
            validate_runtime_database(runtime)
            with pytest.raises(RuntimeError, match="restricted"):
                validate_runtime_database(owner)
            store = WorkspaceStore(runtime)
            first, second = [store.provision(Identity("https://auth.example.test", name, f"{name}@example.test", name, True)) for name in ("first", "second")]
            with runtime.begin() as connection:
                assert connection.execute(select(schema.workspace_settings)).all() == []
                scope_workspace(connection, first.workspace_id)
                assert [row.workspace_id for row in connection.execute(select(schema.workspace_settings))] == [first.workspace_id]
                assert connection.execute(select(schema.workspace_settings).where(schema.workspace_settings.c.workspace_id == second.workspace_id)).all() == []
            with runtime.begin() as connection:
                assert connection.execute(select(schema.workspace_settings)).all() == []
            with pytest.raises(DBAPIError):
                with runtime.begin() as connection:
                    scope_workspace(connection, first.workspace_id)
                    connection.execute(insert(schema.provider_credentials).values(workspace_id=second.workspace_id, provider="openai", label="denied", ciphertext=b"synthetic", key_suffix="0000"))
            with runtime.begin() as connection:
                scope_workspace(connection, second.workspace_id)
                assert len(connection.execute(select(schema.workspace_settings)).all()) == 1
        finally:
            runtime.dispose()
    finally:
        if created:
            with owner.begin() as connection:
                connection.exec_driver_sql("DROP SCHEMA smartroute CASCADE")
                connection.exec_driver_sql("DROP SCHEMA neon_auth CASCADE")
        owner.dispose()