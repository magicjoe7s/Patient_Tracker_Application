"""Persist the last successful reminder display time.

Revision ID: 0007_reminder_shown_state
Revises: 0006_problem_lineage
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_reminder_shown_state"
down_revision: str | None = "0006_problem_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional state without changing any existing reminder schedule."""
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(sa.Column("last_shown_at", sa.String(40), nullable=True))


def downgrade() -> None:
    """Drop display history while retaining reminder schedules and lifecycle state."""
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_column("last_shown_at")
