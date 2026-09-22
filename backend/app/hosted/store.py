"""Require an authenticated workspace context for every hosted data operation."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, Text, cast, delete, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import RuntimeSettings
from app.hosted import schema
from app.hosted.identity import Identity
from app.hosted.config import HostedSettings
from app.hosted.models import CredentialCreate, ModelConfiguration
from app.hosted.secrets import decrypt_provider_key, encrypt_provider_key, hash_api_key, new_api_key


@dataclass(frozen=True)
class Principal:
    """Identify a server-resolved workspace and its authentication privileges."""

    workspace_id: UUID
    user_id: UUID
    auth_type: str
    email_verified: bool = False
    api_key_id: UUID | None = None


def _upsert(connection: Any, table: Any) -> Any:
    """Use the matching conflict-capable insert for PostgreSQL or isolated SQLite tests."""
    return sqlite_insert(table) if connection.dialect.name == "sqlite" else postgres_insert(table)


def _request(row: Any, *, detail: bool = False) -> dict[str, Any]:
    """Keep the existing frontend response contract while storing structured PostgreSQL data."""
    result = dict(row)
    result.pop("workspace_id", None)
    result.pop("api_key_id", None)
    if isinstance(result.get("created_at"), datetime):
        created = result["created_at"]
        result["created_at"] = (created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)).isoformat()
    for name in ("confidence", "actual_cost_usd", "reference_cost_usd"):
        if name in result and result[name] is not None:
            result[name] = float(result[name])
    if detail:
        result["prompt_full"] = json.dumps(result.pop("messages"), ensure_ascii=False)
        result["features_json"] = json.dumps(result.pop("features"))
        result["answer_full"] = result.pop("answer")
    else:
        for name in ("messages", "features", "answer"):
            result.pop(name, None)
    return result


class WorkspaceStore:
    """Keep tenant predicates at the persistence boundary, not just in HTTP handlers."""

    def __init__(self, engine: Engine) -> None:
        """Share the bounded database pool without sharing a connection between requests."""
        self.engine = engine

    def neon_profile(self, identity: Identity) -> Identity:
        """Resolve email verification from Neon's managed user record, not client profile input."""
        with self.engine.connect() as connection:
            row = connection.execute(text(
                'SELECT email, name, "emailVerified" FROM neon_auth."user" WHERE id = :subject'
            ), {"subject": identity.subject}).mappings().first()
        if row is None:
            raise PermissionError("The authenticated account is no longer available.")
        return Identity(identity.issuer, identity.subject, row["email"], (row["name"] or row["email"])[:160], row["emailVerified"] is True)

    def provision(self, identity: Identity) -> Principal:
        """Idempotently create one private workspace for a verified issuer/subject pair."""
        with self.engine.begin() as connection:
            statement = _upsert(connection, schema.users).values(
                id=uuid4(), auth_issuer=identity.issuer, auth_subject=identity.subject,
                email=identity.email, display_name=identity.display_name,
            ).on_conflict_do_update(
                index_elements=["auth_issuer", "auth_subject"],
                set_={"email": identity.email, "display_name": identity.display_name},
            ).returning(schema.users.c.id)
            user_id = connection.execute(statement).scalar_one()
            connection.execute(_upsert(connection, schema.workspaces).values(
                id=uuid4(), owner_id=user_id, name=f"{identity.display_name[:70]}'s workspace", plan="free",
            ).on_conflict_do_nothing(index_elements=["owner_id"]))
            workspace_id = connection.execute(select(schema.workspaces.c.id).where(schema.workspaces.c.owner_id == user_id)).scalar_one()
            connection.execute(_upsert(connection, schema.workspace_settings).values(
                workspace_id=workspace_id,
            ).on_conflict_do_nothing(index_elements=["workspace_id"]))
        return Principal(workspace_id, user_id, "session", identity.email_verified)

    def workspace(self, actor: Principal) -> dict[str, Any]:
        """Read the resolved workspace, without exposing identity or key material to SDK keys."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.workspaces).where(
                schema.workspaces.c.id == actor.workspace_id,
                schema.workspaces.c.owner_id == actor.user_id,
            )).mappings().one()
            user = connection.execute(select(schema.users.c.id, schema.users.c.email, schema.users.c.display_name).where(
                schema.users.c.id == actor.user_id,
            )).mappings().one() if actor.auth_type == "session" else None
        return {
            "workspace": {"id": str(row["id"]), "name": row["name"], "plan": row["plan"]},
            "user": {**dict(user), "id": str(user["id"]), "email_verified": actor.email_verified} if user else None,
            "auth_type": actor.auth_type,
        }

    def create_api_key(self, actor: Principal, name: str, expires_in_days: int) -> dict[str, Any]:
        """Create a one-time plaintext key, storing only its hash and display prefix."""
        if actor.auth_type != "session" or not actor.email_verified:
            raise PermissionError("A verified owner session is required.")
        if not name.strip() or len(name) > 80 or not 1 <= expires_in_days <= 365:
            raise ValueError("Invalid key name or expiration.")
        token, digest, prefix = new_api_key()
        now = datetime.now(timezone.utc)
        values = {
            "id": uuid4(), "workspace_id": actor.workspace_id, "name": name.strip(),
            "key_hash": digest, "key_prefix": prefix, "created_at": now,
            "expires_at": now + timedelta(days=expires_in_days),
        }
        with self.engine.begin() as connection:
            connection.execute(select(schema.workspaces.c.id).where(schema.workspaces.c.id == actor.workspace_id).with_for_update()).scalar_one()
            count = connection.execute(select(func.count()).select_from(schema.api_keys).where(
                schema.api_keys.c.workspace_id == actor.workspace_id,
                schema.api_keys.c.revoked_at.is_(None),
                or_(schema.api_keys.c.expires_at.is_(None), schema.api_keys.c.expires_at > now),
            )).scalar_one()
            if count >= 25:
                raise ValueError("Revoke an existing key before creating another; maximum 25 active keys.")
            connection.execute(insert(schema.api_keys).values(**values))
        return {"id": str(values["id"]), "name": values["name"], "key_prefix": prefix, "created_at": now, "expires_at": values["expires_at"], "key": token}

    def list_api_keys(self, actor: Principal) -> list[dict[str, Any]]:
        """List only non-secret key metadata for this workspace."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        columns = [schema.api_keys.c[name] for name in ("id", "name", "key_prefix", "created_at", "last_used_at", "expires_at", "revoked_at")]
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(*columns).where(
                schema.api_keys.c.workspace_id == actor.workspace_id,
            ).order_by(schema.api_keys.c.created_at.desc())).mappings()]

    def revoke_api_key(self, actor: Principal, key_id: UUID) -> bool:
        """Revoke a workspace key without deleting its audit metadata."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        with self.engine.begin() as connection:
            result = connection.execute(update(schema.api_keys).where(
                schema.api_keys.c.workspace_id == actor.workspace_id, schema.api_keys.c.id == key_id,
            ).values(revoked_at=datetime.now(timezone.utc)))
            return result.rowcount > 0

    def authenticate_api_key(self, token: str) -> Principal | None:
        """Resolve a well-formed, unexpired, unrevoked key to its stored workspace."""
        if not re.fullmatch(r"sr_[A-Za-z0-9_-]{43}", token):
            return None
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(select(
                schema.api_keys.c.id, schema.api_keys.c.workspace_id, schema.workspaces.c.owner_id,
            ).join(schema.workspaces, schema.workspaces.c.id == schema.api_keys.c.workspace_id).where(
                schema.api_keys.c.key_hash == hash_api_key(token), schema.api_keys.c.revoked_at.is_(None),
                or_(schema.api_keys.c.expires_at.is_(None), schema.api_keys.c.expires_at > now),
            )).mappings().first()
            if row is None:
                return None
            connection.execute(update(schema.api_keys).where(schema.api_keys.c.id == row["id"]).values(last_used_at=now))
            return Principal(row["workspace_id"], row["owner_id"], "api_key", api_key_id=row["id"])

    def settings(self, actor: Principal) -> RuntimeSettings:
        """Read only the selected workspace's editable routing configuration."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.workspace_settings).where(
                schema.workspace_settings.c.workspace_id == actor.workspace_id,
            )).mappings().one()
        return RuntimeSettings(**{
            name: float(row[name]) if "price" in name or name == "confidence_threshold" else row[name]
            for name in RuntimeSettings.model_fields
        })

    def update_settings(self, actor: Principal, changes: RuntimeSettings) -> RuntimeSettings:
        """Update owned configuration without modifying process-global legacy settings."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        updates = changes.model_dump(exclude_unset=True)
        if updates.get("max_escalations", 0) > 2:
            raise ValueError("At most two escalation steps are supported.")
        if updates:
            with self.engine.begin() as connection:
                connection.execute(update(schema.workspace_settings).where(
                    schema.workspace_settings.c.workspace_id == actor.workspace_id,
                ).values(**updates))
        return self.settings(actor)

    def list_requests(self, actor: Principal, limit: int = 50, offset: int = 0, **filters: Any) -> dict[str, Any]:
        """Apply the workspace predicate before filtering and paginating request summaries."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination.")
        conditions = [schema.requests.c.workspace_id == actor.workspace_id]
        for name, column in (("tier", "tier_final"), ("escalated", "escalated"), ("source", "source")):
            if filters.get(name) is not None:
                conditions.append(schema.requests.c[column] == filters[name])
        if filters.get("feedback") is not None:
            conditions.append(schema.requests.c.feedback.is_(None) if filters["feedback"] == 0 else schema.requests.c.feedback == filters["feedback"])
        if filters.get("search"):
            escaped = filters["search"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(or_(cast(schema.requests.c.messages, Text).ilike(f"%{escaped}%", escape="\\"), schema.requests.c.answer.ilike(f"%{escaped}%", escape="\\")))
        columns = [column for column in schema.requests.c if column.name not in ("messages", "features", "answer")]
        with self.engine.connect() as connection:
            total = connection.execute(select(func.count()).select_from(schema.requests).where(*conditions)).scalar_one()
            rows = connection.execute(select(*columns).where(*conditions).order_by(
                schema.requests.c.created_at.desc(), schema.requests.c.id.desc(),
            ).limit(limit).offset(offset)).mappings().all()
        return {"items": [_request(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def get_request(self, actor: Principal, request_id: str) -> dict[str, Any] | None:
        """Hide another workspace's record exactly like an unknown request ID."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.requests).where(
                schema.requests.c.workspace_id == actor.workspace_id, schema.requests.c.id == request_id,
            )).mappings().first()
            attempts = connection.execute(select(schema.request_attempts).where(
                schema.request_attempts.c.workspace_id == actor.workspace_id,
                schema.request_attempts.c.request_id == request_id,
            ).order_by(schema.request_attempts.c.sequence)).mappings().all() if row else []
        if not row:
            return None
        result = _request(row, detail=True)
        result["attempts"] = [{name: float(value) if name == "cost_usd" and value is not None else value for name, value in attempt.items() if name not in ("workspace_id", "request_id")} for attempt in attempts]
        return result

    def set_feedback(self, actor: Principal, request_id: str, score: int, note: str | None) -> bool:
        """Update feedback only when the request belongs to the authenticated workspace."""
        if type(score) is not int or score not in (-1, 1):
            raise ValueError("Feedback must be -1 or 1.")
        with self.engine.begin() as connection:
            result = connection.execute(update(schema.requests).where(
                schema.requests.c.workspace_id == actor.workspace_id, schema.requests.c.id == request_id,
                schema.requests.c.status == "completed",
            ).values(feedback=score, feedback_note=note))
            return result.rowcount > 0

    def stats_rows(self, actor: Principal, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Read scoped aggregate inputs without loading prompt/answer text."""
        names = ("created_at", "tier_final", "escalated", "feedback", "routing_mode", "latency_ms", "actual_cost_usd", "reference_cost_usd")
        with self.engine.connect() as connection:
            rows = connection.execute(select(*(schema.requests.c[name] for name in names)).where(
                schema.requests.c.workspace_id == actor.workspace_id,
                schema.requests.c.status == "completed",
                schema.requests.c.created_at >= start, schema.requests.c.created_at <= end,
            )).mappings().all()
        return [_request(row) for row in rows]

    def training_rows(self, actor: Principal) -> list[dict[str, Any]]:
        """Read labelled features only from the actor's workspace."""
        with self.engine.connect() as connection:
            rows = connection.execute(select(schema.requests.c.features, schema.requests.c.tier_final, schema.requests.c.feedback).where(
                schema.requests.c.workspace_id == actor.workspace_id, schema.requests.c.feedback.in_([-1, 1]),
                schema.requests.c.status == "completed",
            )).mappings().all()
        return [{"features_json": json.dumps(row["features"]), "tier_final": row["tier_final"], "feedback": row["feedback"]} for row in rows]

    def runs(self, actor: Principal, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List only this workspace's completed Test Lab summaries."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination.")
        condition = schema.testlab_runs.c.workspace_id == actor.workspace_id
        columns = [column for column in schema.testlab_runs.c if column.name not in ("workspace_id", "results")]
        with self.engine.connect() as connection:
            total = connection.execute(select(func.count()).select_from(schema.testlab_runs).where(condition)).scalar_one()
            rows = connection.execute(select(*columns).where(condition).order_by(schema.testlab_runs.c.created_at.desc()).limit(limit).offset(offset)).mappings().all()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def training_status(self, actor: Principal) -> dict[str, Any]:
        """Return metadata for only this workspace's trusted classifier artifact."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.router_models.c.metadata).where(
                schema.router_models.c.workspace_id == actor.workspace_id,
            )).scalar_one_or_none()
        return row or {"trained": False}

    def tiers(self, actor: Principal) -> list[dict[str, Any]]:
        """Read only owned model configuration, without loading encrypted credentials."""
        with self.engine.connect() as connection:
            rows = connection.execute(select(
                schema.models.c.tier, schema.models.c.model, schema.models.c.enabled,
                schema.models.c.input_price_per_1k, schema.models.c.output_price_per_1k,
                schema.provider_credentials.c.provider,
            ).join(schema.provider_credentials, schema.models.c.credential_id == schema.provider_credentials.c.id).where(
                schema.models.c.workspace_id == actor.workspace_id,
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
            )).mappings().all()
        return [{
            "name": row["tier"], "model": row["model"], "enabled": row["enabled"],
            "provider": row["provider"], "base_url": "", "reachable": False,
            "input_price_per_1k": float(row["input_price_per_1k"]),
            "output_price_per_1k": float(row["output_price_per_1k"]),
        } for row in rows]

    def credentials(self, actor: Principal) -> list[dict[str, Any]]:
        """List only non-secret provider-credential metadata for the owner."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        columns = [schema.provider_credentials.c[name] for name in ("id", "provider", "label", "key_suffix", "created_at")]
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(*columns).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
            ).order_by(schema.provider_credentials.c.created_at)).mappings()]

    def create_credential(self, actor: Principal, body: CredentialCreate, configured: HostedSettings) -> dict[str, Any]:
        """Encrypt a provider key before storing it and return only display metadata."""
        if actor.auth_type != "session" or not actor.email_verified:
            raise PermissionError("A verified owner session is required.")
        credential_id = uuid4()
        secret = body.api_key.get_secret_value()
        ciphertext = encrypt_provider_key(configured, actor.workspace_id, body.provider, secret)
        with self.engine.begin() as connection:
            connection.execute(select(schema.workspaces.c.id).where(schema.workspaces.c.id == actor.workspace_id).with_for_update()).scalar_one()
            count = connection.execute(select(func.count()).select_from(schema.provider_credentials).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
            )).scalar_one()
            if count >= 10:
                raise ValueError("At most 10 provider credentials are allowed per workspace.")
            connection.execute(insert(schema.provider_credentials).values(
                id=credential_id, workspace_id=actor.workspace_id, provider=body.provider,
                label=body.label, ciphertext=ciphertext, key_suffix=secret[-4:],
            ))
        return {"id": str(credential_id), "provider": body.provider, "label": body.label, "key_suffix": secret[-4:]}

    def replace_credential(self, actor: Principal, credential_id: UUID, secret: str, configured: HostedSettings) -> bool:
        """Rotate an owned secret without exposing or changing its provider identity."""
        if actor.auth_type != "session" or not actor.email_verified:
            raise PermissionError("A verified owner session is required.")
        with self.engine.begin() as connection:
            provider = connection.execute(select(schema.provider_credentials.c.provider).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
                schema.provider_credentials.c.id == credential_id,
            )).scalar_one_or_none()
            if provider is None:
                return False
            connection.execute(update(schema.provider_credentials).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id, schema.provider_credentials.c.id == credential_id,
            ).values(ciphertext=encrypt_provider_key(configured, actor.workspace_id, provider, secret), key_suffix=secret[-4:]))
        return True

    def delete_credential(self, actor: Principal, credential_id: UUID) -> bool:
        """Remove one owned credential and its configured models via the schema's cascade."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        with self.engine.begin() as connection:
            result = connection.execute(delete(schema.provider_credentials).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
                schema.provider_credentials.c.id == credential_id,
            ))
            return result.rowcount > 0

    def configure_model(self, actor: Principal, tier: str, body: ModelConfiguration) -> dict[str, Any]:
        """Upsert one tier only when its credential belongs to the same verified owner."""
        if actor.auth_type != "session" or not actor.email_verified:
            raise PermissionError("A verified owner session is required.")
        if tier not in ("small", "medium", "large"):
            raise ValueError("Invalid model tier.")
        with self.engine.begin() as connection:
            owned = connection.execute(select(schema.provider_credentials.c.id).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
                schema.provider_credentials.c.id == body.credential_id,
            )).scalar_one_or_none()
            if owned is None:
                raise LookupError("Provider credential not found.")
            values = body.model_dump()
            connection.execute(_upsert(connection, schema.models).values(
                id=uuid4(), workspace_id=actor.workspace_id, tier=tier, **values,
            ).on_conflict_do_update(index_elements=["workspace_id", "tier"], set_=values))
        return {"tier": tier, **body.model_dump(mode="json")}

    def delete_model(self, actor: Principal, tier: str) -> bool:
        """Remove only the selected workspace's tier mapping."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        with self.engine.begin() as connection:
            return connection.execute(delete(schema.models).where(
                schema.models.c.workspace_id == actor.workspace_id, schema.models.c.tier == tier,
            )).rowcount > 0

    def model_rows(self, actor: Principal) -> list[dict[str, Any]]:
        """Return owned model configuration without ciphertext or plaintext credentials."""
        with self.engine.connect() as connection:
            rows = connection.execute(select(schema.models, schema.provider_credentials.c.provider).join(
                schema.provider_credentials, schema.models.c.credential_id == schema.provider_credentials.c.id,
            ).where(schema.models.c.workspace_id == actor.workspace_id, schema.provider_credentials.c.workspace_id == actor.workspace_id)).mappings().all()
        return [{name: value for name, value in row.items() if name != "workspace_id"} for row in rows]

    def provider_key(self, actor: Principal, credential_id: UUID, configured: HostedSettings) -> tuple[str, str]:
        """Decrypt only an owned credential immediately before a provider operation."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.provider_credentials.c.provider, schema.provider_credentials.c.ciphertext).where(
                schema.provider_credentials.c.workspace_id == actor.workspace_id,
                schema.provider_credentials.c.id == credential_id,
            )).mappings().first()
        if row is None:
            raise LookupError("Provider credential not found.")
        return row["provider"], decrypt_provider_key(configured, actor.workspace_id, row["provider"], row["ciphertext"])

    def save_model(self, actor: Principal, artifact: bytes, metadata: dict[str, Any], feature_order: list[str]) -> None:
        """Persist a server-trained classifier only under the actor's workspace."""
        if actor.auth_type != "session":
            raise PermissionError("An owner session is required.")
        with self.engine.begin() as connection:
            values = {"artifact": artifact, "metadata": metadata, "feature_order": feature_order, "trained_at": datetime.now(timezone.utc)}
            connection.execute(_upsert(connection, schema.router_models).values(workspace_id=actor.workspace_id, **values).on_conflict_do_update(index_elements=["workspace_id"], set_=values))

    def classifier(self, actor: Principal) -> dict[str, Any] | None:
        """Read only the current workspace's server-generated routing artifact."""
        with self.engine.connect() as connection:
            row = connection.execute(select(schema.router_models.c.artifact, schema.router_models.c.feature_order).where(
                schema.router_models.c.workspace_id == actor.workspace_id,
            )).mappings().first()
        return dict(row) if row else None

    def record_inference(self, actor: Principal, row: dict[str, Any], attempts: list[dict[str, Any]]) -> None:
        """Atomically persist a request and all its attempts with server-supplied tenant identity."""
        with self.engine.begin() as connection:
            connection.execute(insert(schema.requests).values(**{**row, "workspace_id": actor.workspace_id, "api_key_id": actor.api_key_id}))
            if attempts:
                connection.execute(insert(schema.request_attempts), [
                    {**attempt, "id": uuid4(), "workspace_id": actor.workspace_id, "request_id": row["id"], "sequence": index + 1}
                    for index, attempt in enumerate(attempts)
                ])

    def record_run(self, actor: Principal, values: dict[str, Any]) -> None:
        """Persist only an authenticated workspace's completed suite summary and results."""
        with self.engine.begin() as connection:
            connection.execute(insert(schema.testlab_runs).values(**{**values, "workspace_id": actor.workspace_id}))