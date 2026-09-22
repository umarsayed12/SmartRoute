## Generate a self-contained, immutable Alembic revision with a purpose docstring.
"""${message}."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply this schema revision."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Reverse this schema revision only when explicitly requested by the operator."""
    ${downgrades if downgrades else "pass"}