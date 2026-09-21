"""Inspect model availability, persist runtime settings, and manage router training."""

import asyncio
import logging
from threading import Lock
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app import config, train as training
from app.config import RuntimeSettings, Tier
from app.schemas import TrainingMetadata

router = APIRouter(prefix="/v1", tags=["admin"])
_training_lock = Lock()
_logger = logging.getLogger(__name__)


async def _reachable(client: httpx.AsyncClient, tier: Tier) -> bool:
    """Check a provider's model list without generating tokens or charging inference."""
    if not tier.enabled or not tier.base_url:
        return False
    try:
        root = tier.base_url.rstrip("/")
        if tier.provider == "ollama":
            response = await client.get(f"{root}/api/tags")
        else:
            if not root.endswith("/v1"):
                root += "/v1"
            key = tier.api_key.get_secret_value()
            response = await client.get(
                f"{root}/models", headers={"Authorization": f"Bearer {key}"} if key else {}
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return False
        models = data.get("models" if tier.provider == "ollama" else "data", [])
        if not isinstance(models, list):
            return False
        return any(
            isinstance(model, dict)
            and tier.model in (model.get("name"), model.get("model"), model.get("id"))
            for model in models
        )
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return False


@router.get("/tiers")
async def get_tiers() -> list[dict[str, Any]]:
    """Return tier configuration and live model availability, excluding API keys."""
    tiers = config.settings.TIERS
    async with httpx.AsyncClient(timeout=2.0) as client:
        reachable = await asyncio.gather(*(_reachable(client, tier) for tier in tiers))
    return [
        {**tier.model_dump(exclude={"api_key"}), "reachable": available}
        for tier, available in zip(tiers, reachable)
    ]


@router.get("/settings", response_model=RuntimeSettings)
def get_settings() -> RuntimeSettings:
    """Return only the editable runtime configuration, never credentials."""
    return config.get_runtime_settings()


@router.put("/settings", response_model=RuntimeSettings)
def put_settings(updates: RuntimeSettings) -> RuntimeSettings:
    """Apply validated partial settings updates after successfully persisting them."""
    try:
        return config.update_runtime_settings(updates)
    except OSError as error:
        _logger.exception("Could not persist runtime settings.")
        raise HTTPException(status_code=500, detail="Could not persist runtime settings.") from error


@router.post("/train")
def train_router() -> dict[str, Any]:
    """Run training in the worker thread, permitting only one admin training job at a time."""
    if not _training_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Router training is already running.")
    try:
        return training.train()
    except (OSError, ValueError) as error:
        _logger.exception("Router training failed.")
        raise HTTPException(status_code=500, detail="Router training failed; see backend logs.") from error
    finally:
        _training_lock.release()


@router.get("/train/status")
def get_training_status() -> dict[str, Any]:
    """Return validated training metadata only when its model artifact is also present."""
    model_path = config.settings.MODEL_PATH
    try:
        if not model_path.is_file():
            return {"trained": False}
        metadata = TrainingMetadata.model_validate_json(
            model_path.with_name("router_model_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError):
        return {"trained": False}
    return metadata.model_dump(mode="json")