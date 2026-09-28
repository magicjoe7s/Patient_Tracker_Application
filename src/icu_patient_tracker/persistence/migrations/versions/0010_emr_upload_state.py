"""Add day-owned EMR handoff state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_emr_upload_state"
down_revision: str | None = "0009_day_sandbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Default every existing day to not uploaded."""
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.add_column(
            sa.Column("emr_uploaded", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Remove the day-owned EMR handoff marker."""
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.drop_column("emr_uploaded")
