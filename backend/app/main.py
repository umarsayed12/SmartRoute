"""Initialize storage, register API routes, and report backend and Ollama health."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api.chat import router as chat_router
from app.api.stats import router as stats_router
from app.config import settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize the request database before the application accepts traffic."""
    db.init_db()
    yield


app = FastAPI(title="SmartRoute", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)
app.include_router(stats_router)


@app.get("/health")
async def health() -> dict[str, str | list[str] | bool]:
    """Return enabled tiers and a one-second-timeout Ollama reachability check."""
    ollama_available = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(
                f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
            )
            response.raise_for_status()
            ollama_available = True
    except httpx.HTTPError:
        pass
    return {
        "status": "ok",
        "tiers": [tier.name for tier in settings.TIERS if tier.enabled],
        "ollama": ollama_available,
    }