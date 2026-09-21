"""Load environment settings and describe the ordered model tiers."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
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