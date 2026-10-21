"""Add groq to provider_credentials check constraint."""

from alembic import op

revision = "0004_add_groq_provider"
down_revision = "0003_tenant_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow groq in addition to openai and anthropic."""
    op.drop_constraint("ck_credentials_provider", "provider_credentials", schema="smartroute", type_="check")
    op.create_check_constraint("ck_credentials_provider", "provider_credentials", "provider IN ('openai', 'anthropic', 'groq')", schema="smartroute")


def downgrade() -> None:
    """Restore the original provider constraint."""
    op.drop_constraint("ck_credentials_provider", "provider_credentials", schema="smartroute", type_="check")
    op.create_check_constraint("ck_credentials_provider", "provider_credentials", "provider IN ('openai', 'anthropic')", schema="smartroute")
