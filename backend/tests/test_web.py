"""Verify direct SPA refreshes, static caching, and separation from authenticated API paths."""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.web import PAGE_ROUTES, mount_frontend


@pytest.mark.asyncio
async def test_spa_refresh_and_api_boundaries(tmp_path: Path) -> None:
    """Every registered page loads HTML, but missing APIs/assets and private files remain errors."""
    (tmp_path / "index.html").write_text("<html>SmartRoute shell</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-hashed.js").write_text("console.log('ready')", encoding="utf-8")
    (tmp_path / ".env").write_text("not-public", encoding="utf-8")
    app = FastAPI()
    @app.get("/v1/example")
    def example() -> dict[str, bool]:
        """Represent an API route registered before static mounting."""
        return {"ok": True}
    mount_frontend(app, tmp_path, required=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        for page in PAGE_ROUTES:
            response = await client.get(f"/{page}")
            assert response.status_code == 200 and "SmartRoute shell" in response.text
            assert response.headers["cache-control"] == "no-cache"
            if page:
                assert (await client.get(f"/{page}/")).status_code == 200
        for path in ("/v1/missing", "/health/missing", "/assets/missing.js", "/.env", "/unknown", "/%2e%2e/.env"):
            response = await client.get(path)
            assert response.status_code == 404 and "SmartRoute shell" not in response.text
        assert (await client.get("/v1/example")).json() == {"ok": True}
        reset = await client.get("/reset-password?token=synthetic-reset-token")
        assert reset.status_code == 200 and "SmartRoute shell" in reset.text
        asset = await client.get("/assets/app-hashed.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]


def test_hosted_frontend_build_is_required(tmp_path: Path) -> None:
    """Fail early rather than deploy an API service with a broken web entry point."""
    with pytest.raises(RuntimeError, match="Frontend build missing"):
        mount_frontend(FastAPI(), tmp_path, required=True)