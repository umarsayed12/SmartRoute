"""Define workspace-owned PostgreSQL tables separately from Neon's managed auth schema."""

from uuid import uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, LargeBinary, MetaData, Numeric, String, Table, Text,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB

SCHEMA = "smartroute"
metadata = MetaData(schema=SCHEMA)
json_type = JSON().with_variant(JSONB, "postgresql")

users = Table(
    "users", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("auth_issuer", String(512), nullable=False),
    Column("auth_subject", String(255), nullable=False),
    Column("email", String(320), nullable=False),
    Column("display_name", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("auth_issuer", "auth_subject", name="uq_users_identity"),
)

workspaces = Table(
    "workspaces", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("owner_id", Uuid, ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("plan", String(20), nullable=False, server_default="free"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("owner_id", name="uq_workspaces_owner"),
    CheckConstraint("plan IN ('free', 'premium')", name="ck_workspaces_plan"),
)

api_keys = Table(
    "api_keys", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(80), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("key_prefix", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_used_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Index("ix_api_keys_workspace", "workspace_id"),
)

provider_credentials = Table(
    "provider_credentials", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(20), nullable=False),
    Column("label", String(80), nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    Column("key_suffix", String(4), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("workspace_id", "id", name="uq_credentials_workspace_id"),
    UniqueConstraint("workspace_id", "provider", "label", name="uq_credentials_label"),
    CheckConstraint("provider IN ('openai', 'anthropic')", name="ck_credentials_provider"),
)

models = Table(
    "models", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("credential_id", Uuid, nullable=False),
    Column("tier", String(20), nullable=False),
    Column("model", String(200), nullable=False),
    Column("input_price_per_1k", Numeric(20, 10), nullable=False),
    Column("output_price_per_1k", Numeric(20, 10), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["workspace_id", "credential_id"],
        [f"{SCHEMA}.provider_credentials.workspace_id", f"{SCHEMA}.provider_credentials.id"],
        name="fk_models_workspace_credential", ondelete="CASCADE",
    ),
    UniqueConstraint("workspace_id", "tier", name="uq_models_workspace_tier"),
    CheckConstraint("tier IN ('small', 'medium', 'large')", name="ck_models_tier"),
    CheckConstraint("input_price_per_1k >= 0 AND output_price_per_1k >= 0", name="ck_models_prices"),
)

workspace_settings = Table(
    "workspace_settings", metadata,
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), primary_key=True),
    Column("confidence_threshold", Numeric(4, 3), nullable=False, server_default="0.6"),
    Column("max_escalations", Integer, nullable=False, server_default="1"),
    Column("reference_input_price_per_1k", Numeric(20, 10), nullable=False, server_default="0.0025"),
    Column("reference_output_price_per_1k", Numeric(20, 10), nullable=False, server_default="0.010"),
    Column("routing_mode_preference", String(30), nullable=False, server_default="auto"),
    CheckConstraint("confidence_threshold >= 0 AND confidence_threshold <= 1", name="ck_settings_confidence"),
    CheckConstraint("max_escalations >= 0 AND max_escalations <= 2", name="ck_settings_escalations"),
    CheckConstraint("reference_input_price_per_1k >= 0 AND reference_output_price_per_1k >= 0", name="ck_settings_prices"),
    CheckConstraint("routing_mode_preference IN ('auto', 'heuristic_only', 'learned_only')", name="ck_settings_preference"),
)

requests = Table(
    "requests", metadata,
    Column("id", String(80), primary_key=True),
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("api_key_id", Uuid),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("prompt_preview", String(200), nullable=False),
    Column("messages", json_type, nullable=False),
    Column("answer", Text, nullable=False),
    Column("features", json_type, nullable=False),
    Column("tier_chosen", String(20), nullable=False),
    Column("tier_final", String(20), nullable=False),
    Column("provider", String(20), nullable=False),
    Column("model", String(200), nullable=False),
    Column("escalated", Boolean, nullable=False),
    Column("confidence", Numeric(6, 5), nullable=False),
    Column("reason", Text, nullable=False),
    Column("routing_mode", String(20), nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("actual_cost_usd", Numeric(20, 10), nullable=False),
    Column("reference_cost_usd", Numeric(20, 10), nullable=False),
    Column("feedback", Integer),
    Column("feedback_note", Text),
    Column("source", String(20), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_requests_workspace_id"),
    CheckConstraint("feedback IS NULL OR feedback IN (-1, 1)", name="ck_requests_feedback"),
    CheckConstraint("source IN ('api', 'playground', 'testlab', 'sdk')", name="ck_requests_source"),
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_requests_confidence"),
    CheckConstraint("prompt_tokens >= 0 AND completion_tokens >= 0 AND latency_ms >= 0", name="ck_requests_usage"),
    CheckConstraint("actual_cost_usd >= 0 AND reference_cost_usd >= 0", name="ck_requests_costs"),
    Index("ix_requests_workspace_created", "workspace_id", "created_at", "id"),
)

request_attempts = Table(
    "request_attempts", metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("workspace_id", Uuid, nullable=False),
    Column("request_id", String(80), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("tier", String(20), nullable=False),
    Column("provider", String(20), nullable=False),
    Column("model", String(200), nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("cost_usd", Numeric(20, 10), nullable=False),
    Column("usage_details", json_type, nullable=False),
    ForeignKeyConstraint(
        ["workspace_id", "request_id"], [f"{SCHEMA}.requests.workspace_id", f"{SCHEMA}.requests.id"],
        name="fk_attempts_workspace_request", ondelete="CASCADE",
    ),
    UniqueConstraint("request_id", "sequence", name="uq_attempts_sequence"),
    CheckConstraint("kind IN ('answer', 'self_check')", name="ck_attempts_kind"),
    CheckConstraint("prompt_tokens >= 0 AND completion_tokens >= 0 AND latency_ms >= 0 AND cost_usd >= 0", name="ck_attempts_usage"),
)

testlab_runs = Table(
    "testlab_runs", metadata,
    Column("run_id", String(80), primary_key=True),
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("suite", String(80), nullable=False),
    Column("mode", String(20), nullable=False),
    Column("prompt_count", Integer, nullable=False),
    Column("summary", json_type, nullable=False),
    Column("results", json_type, nullable=False),
    Index("ix_testlab_workspace_created", "workspace_id", "created_at", "run_id"),
)

router_models = Table(
    "router_models", metadata,
    Column("workspace_id", Uuid, ForeignKey(f"{SCHEMA}.workspaces.id", ondelete="CASCADE"), primary_key=True),
    Column("artifact", LargeBinary, nullable=False),
    Column("metadata", json_type, nullable=False),
    Column("feature_order", json_type, nullable=False),
    Column("trained_at", DateTime(timezone=True), nullable=False),
)