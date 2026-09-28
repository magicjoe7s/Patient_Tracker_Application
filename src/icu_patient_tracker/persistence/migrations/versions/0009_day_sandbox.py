"""Add day-owned Sandbox Markdown."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_day_sandbox"
down_revision: str | None = "0008_canonical_soap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an empty lossless scratch field to every existing day."""
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.add_column(sa.Column("sandbox_text", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    """Remove the Slice 9 scratch field."""
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.drop_column("sandbox_text")
