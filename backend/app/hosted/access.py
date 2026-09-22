"""Apply transaction-local tenant context and verify public runtime database privileges."""

from uuid import UUID

from sqlalchemy import Connection, Engine, text

TENANT_TABLES = ("provider_credentials", "models", "workspace_settings", "requests", "request_attempts", "testlab_runs", "router_models")


def scope_workspace(connection: Connection, workspace_id: UUID) -> None:
    """Use transaction-local settings compatible with Neon transaction pooling."""
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('smartroute.workspace_id', :workspace, true)"), {"workspace": str(workspace_id)})


def validate_runtime_database(engine: Engine) -> None:
    """Fail closed for owner/bypass roles, missing policies, or unscoped access to tenant data."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Public hosting requires PostgreSQL with the runtime security migration.")
    with engine.begin() as connection:
        role = connection.execute(text("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user")).mappings().one()
        if any(role.values()) or connection.execute(text("SELECT has_schema_privilege(current_user, 'smartroute', 'CREATE')")).scalar_one():
            raise RuntimeError("Use the restricted smartroute_runtime database role, not an owner or bypass role.")
        rows = connection.execute(text("""
            SELECT c.relname, c.relrowsecurity,
                   pg_has_role(current_user, c.relowner, 'MEMBER') AS owns_table,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policy_count,
                   EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid
                           AND p.polname = 'workspace_isolation' AND p.polqual IS NOT NULL
                           AND p.polwithcheck IS NOT NULL AND p.polcmd = '*') AS scoped_policy
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'smartroute' AND c.relkind = 'r'
        """)).mappings().all()
        tables = {row["relname"]: row for row in rows}
        for name in TENANT_TABLES:
            row = tables.get(name)
            if not row or not row["relrowsecurity"] or row["owns_table"] or row["policy_count"] != 1 or not row["scoped_policy"]:
                raise RuntimeError("The runtime database role and tenant policies have not passed deployment checks.")
        connection.execute(text("SELECT set_config('smartroute.workspace_id', '', true)"))
        for name in TENANT_TABLES:
            if connection.execute(text(f'SELECT 1 FROM smartroute."{name}" LIMIT 1')).first() is not None:
                raise RuntimeError("Unscoped database access returned tenant data.")
        connection.execute(text('SELECT id, email, name, "emailVerified" FROM neon_auth."user" WHERE false'))


def main() -> None:
    """Check only process-supplied runtime credentials without loading a local environment file."""
    from app.hosted.config import HostedSettings, database_engine

    engine = None
    try:
        engine = database_engine(HostedSettings(_env_file=None))
        validate_runtime_database(engine)
    except Exception as error:
        raise SystemExit(f"Runtime database check failed ({type(error).__name__}). Verify the migration, restricted role, and auth-profile grants; credentials were not displayed.") from None
    finally:
        if engine is not None:
            engine.dispose()
    print("Runtime database role and tenant policy checks passed.")


if __name__ == "__main__":
    main()