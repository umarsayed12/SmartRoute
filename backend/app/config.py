"""Load tier configuration and persist the gateway's editable runtime settings."""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Tier(BaseModel):
    """Describe a provider, model, and token prices for one routing tier."""

    name: Literal["small", "medium", "large"]
    provider: Literal["ollama", "openai_compatible"]
    model: str
    base_url: str
    api_key: SecretStr = SecretStr("")
    input_price_per_1k: float = Field(default=0.0, ge=0)
    output_price_per_1k: float = Field(default=0.0, ge=0)
    enabled: bool = True


class Settings(BaseSettings):
    """Read backend settings from environment variables and backend/.env."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LARGE_MODEL: str = ""
    LARGE_BASE_URL: str = ""
    LARGE_API_KEY: SecretStr = SecretStr("")
    LARGE_INPUT_PRICE: float = Field(default=0.0, ge=0)
    LARGE_OUTPUT_PRICE: float = Field(default=0.0, ge=0)
    REFERENCE_INPUT_PRICE_PER_1K: float = Field(default=0.0025, ge=0)
    REFERENCE_OUTPUT_PRICE_PER_1K: float = Field(default=0.010, ge=0)
    CONFIDENCE_THRESHOLD: float = Field(default=0.6, ge=0, le=1)
    MAX_ESCALATIONS: int = Field(default=1, ge=0)
    ROUTING_MODE_PREFERENCE: Literal["auto", "heuristic_only", "learned_only"] = "auto"
    DB_PATH: Path = Path("data/smartroute.db")
    MODEL_PATH: Path = Path("data/router_model.joblib")

    @property
    def TIERS(self) -> list[Tier]:
        """Return tiers in ascending order, retaining a disabled large tier."""
        return [
            Tier(
                name="small",
                provider="ollama",
                model="qwen2.5:1.5b",
                base_url=self.OLLAMA_BASE_URL,
            ),
            Tier(
                name="medium",
                provider="ollama",
                model="qwen2.5:7b",
                base_url=self.OLLAMA_BASE_URL,
            ),
            Tier(
                name="large",
                provider="openai_compatible",
                model=self.LARGE_MODEL,
                base_url=self.LARGE_BASE_URL,
                api_key=self.LARGE_API_KEY,
                input_price_per_1k=self.LARGE_INPUT_PRICE,
                output_price_per_1k=self.LARGE_OUTPUT_PRICE,
                enabled=bool(self.LARGE_MODEL),
            ),
        ]

    def get_tier(self, name: str) -> Tier:
        """Find a tier, resolving disabled large requests to medium."""
        resolved_name = "medium" if name == "large" and not self.LARGE_MODEL else name
        for tier in self.TIERS:
            if tier.name == resolved_name:
                return tier
        raise ValueError(f"Unknown tier: {name}")


settings = Settings()


class RuntimeSettings(BaseModel):
    """Validate the non-secret settings that may be changed through the admin API."""

    model_config = ConfigDict(extra="forbid")

    confidence_threshold: float = Field(default=0.6, ge=0, le=1, strict=True)
    max_escalations: int = Field(default=1, ge=0, strict=True)
    reference_input_price_per_1k: float = Field(default=0.0025, ge=0, allow_inf_nan=False, strict=True)
    reference_output_price_per_1k: float = Field(default=0.010, ge=0, allow_inf_nan=False, strict=True)
    routing_mode_preference: Literal["auto", "heuristic_only", "learned_only"] = "auto"


_runtime_lock = RLock()
_logger = logging.getLogger(__name__)


def get_runtime_settings() -> RuntimeSettings:
    """Return a validated snapshot of the shared in-memory runtime settings."""
    with _runtime_lock:
        return RuntimeSettings(**{
            name: getattr(settings, name.upper()) for name in RuntimeSettings.model_fields
        })


def _apply_runtime_settings(values: RuntimeSettings) -> None:
    """Mutate the shared settings object so existing module references see updates."""
    for name, value in values.model_dump(exclude_unset=True).items():
        setattr(settings, name.upper(), value)


def load_runtime_settings() -> None:
    """Apply valid persisted overrides at startup, retaining current values on failure."""
    path = settings.DB_PATH.with_name("settings.json")
    with _runtime_lock:
        if not path.exists():
            return
        try:
            values = RuntimeSettings.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            _logger.warning("Ignoring invalid or unreadable runtime settings.")
            return
        _apply_runtime_settings(values)


def update_runtime_settings(updates: RuntimeSettings) -> RuntimeSettings:
    """Merge partial updates, atomically persist them, then change in-memory values."""
    with _runtime_lock:
        values = RuntimeSettings(**{
            **get_runtime_settings().model_dump(),
            **updates.model_dump(exclude_unset=True),
        })
        path = settings.DB_PATH.with_name("settings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=path.parent) as directory:
            staged = Path(directory) / "settings.json"
            staged.write_text(values.model_dump_json(indent=2), encoding="utf-8")
            staged.replace(path)
        _apply_runtime_settings(values)
        return values