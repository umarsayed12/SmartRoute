"""Run migrations only for SmartRoute's schema using the direct database connection."""

from alembic import context
from sqlalchemy import text

from app.hosted.config import HostedSettings, database_engine, database_url
from app.hosted.schema import SCHEMA, metadata


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Exclude Neon's auth tables and every unrelated database schema from autogeneration."""
    if type_ == "schema":
        return name == SCHEMA
    return parent_names.get("schema_name", SCHEMA) == SCHEMA


def run_migrations() -> None:
    """Configure online or offline migration execution without storing a URL in alembic.ini."""
    configured = HostedSettings()
    options = {
        "target_metadata": metadata,
        "include_schemas": True,
        "include_name": include_name,
        "version_table_schema": SCHEMA,
        "compare_type": True,
    }
    if context.is_offline_mode():
        context.configure(
            url=database_url(configured, direct=True), literal_binds=True,
            dialect_opts={"paramstyle": "named"}, **options,
        )
        with context.begin_transaction():
            context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            context.run_migrations()
        return

    engine = database_engine(configured, direct=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
            connection.commit()
            context.configure(connection=connection, **options)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()