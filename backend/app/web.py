"""Serve the compiled React application without turning API or asset errors into HTML."""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "static"
PAGE_ROUTES = {"", "dashboard", "requests", "testlab", "settings", "models", "account", "integration", "reset-password"}


class FrontendFiles(StaticFiles):
    """Return the SPA shell only for registered client pages and safe static files."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Keep missing assets, private paths, and unknown API routes out of the SPA fallback."""
        normalized = "" if path == "." else path.replace("\\", "/").strip("/")
        if any(part.startswith(".") for part in normalized.split("/")) or normalized.split("/")[0] in {"v1", "health", "docs", "redoc", "openapi.json"}:
            raise HTTPException(status_code=404)
        response = await super().get_response("index.html" if normalized in PAGE_ROUTES else path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if normalized.startswith("assets/") else "no-cache"
        return response


def mount_frontend(application: FastAPI, directory: Path = WEB_DIRECTORY, *, required: bool = False) -> None:
    """Mount generated files last; require a completed build for public deployment."""
    if not (directory / "index.html").is_file():
        if required:
            raise RuntimeError("Frontend build missing. Build the frontend into backend/static before deployment.")
        return
    application.mount("/", FrontendFiles(directory=directory, html=False), name="frontend")