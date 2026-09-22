"""Share an ASGI client and isolate request data and trained model artifacts in tests."""

from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.config import RuntimeSettings
from app.main import app
from app.hosted import schema
from app.hosted.store import WorkspaceStore


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point database and model operations at separate temporary paths for every test."""
    path = tmp_path / "smartroute.db"
    monkeypatch.setattr(db.settings, "APP_MODE", "local")
    monkeypatch.setattr(db.settings, "DB_PATH", path)
    monkeypatch.setattr(db.settings, "MODEL_PATH", tmp_path / "router_model.joblib")
    for name, value in RuntimeSettings().model_dump().items():
        monkeypatch.setattr(db.settings, name.upper(), value)
    return path


@pytest_asyncio.fixture
async def client(isolated_database: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Run application startup and use in-process HTTP with an isolated database."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as connection:
            yield connection


@pytest.fixture
def mock_http(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], None]:
    """Replace outbound HTTP with a per-test transport, keeping client behavior."""
    original_client = httpx.AsyncClient

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        """Route subsequent async clients through the supplied handler."""
        def create_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            """Build a real async client with an in-memory HTTP transport."""
            return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", create_client)

    return install


@pytest.fixture
def store() -> Iterator[WorkspaceStore]:
    """Build the hosted schema in an isolated test-only SQL database."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}, execution_options={"schema_translate_map": {schema.SCHEMA: None}})
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        schema.metadata.create_all(connection)
    yield WorkspaceStore(engine)
    engine.dispose()