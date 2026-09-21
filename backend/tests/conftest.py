"""Share an ASGI client and isolate request data and trained model artifacts in tests."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app import db
from app.main import app


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point database and model operations at separate temporary paths for every test."""
    path = tmp_path / "smartroute.db"
    monkeypatch.setattr(db.settings, "DB_PATH", path)
    monkeypatch.setattr(db.settings, "MODEL_PATH", tmp_path / "router_model.joblib")
    return path


@pytest_asyncio.fixture
async def client(isolated_database: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Run application startup and use in-process HTTP with an isolated database."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as connection:
            yield connection