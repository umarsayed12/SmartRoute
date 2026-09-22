"""Add transaction-scoped row policies to private workspace data tables."""

from alembic import op

revision = "0003_tenant_policies"
down_revision = "0002_owned_inference"
branch_labels = None
depends_on = None
TABLES = ("provider_credentials", "models", "workspace_settings", "requests", "request_attempts", "testlab_runs", "router_models")


def upgrade() -> None:
    """Require explicit workspace context for non-owner runtime access to tenant data."""
    for name in TABLES:
        op.execute(f'ALTER TABLE smartroute."{name}" ENABLE ROW LEVEL SECURITY')
        predicate = "workspace_id = NULLIF(current_setting('smartroute.workspace_id', true), '')::uuid"
        op.execute(f'CREATE POLICY workspace_isolation ON smartroute."{name}" USING ({predicate}) WITH CHECK ({predicate})')


def downgrade() -> None:
    """Remove tenant policies only during an explicitly requested rollback."""
    for name in reversed(TABLES):
        op.execute(f'DROP POLICY workspace_isolation ON smartroute."{name}"')
        op.execute(f'ALTER TABLE smartroute."{name}" DISABLE ROW LEVEL SECURITY')