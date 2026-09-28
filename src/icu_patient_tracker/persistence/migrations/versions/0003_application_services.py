"""Add fields required by the application-service use cases.

Revision ID: 0003_application_services
Revises: 0002_task_lineage
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_application_services"
down_revision: str | None = "0002_task_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add service-facing metadata while preserving existing records."""
    with op.batch_alter_table("patients") as batch_op:
        batch_op.add_column(
            sa.Column("one_line_summary", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("code_status", sa.String(18), server_default="full_code", nullable=False)
        )
        batch_op.add_column(sa.Column("blood_type", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("acuity", sa.String(8), server_default="stable", nullable=False)
        )
        batch_op.add_column(
            sa.Column("active_order", sa.Integer(), server_default="0", nullable=False)
        )
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.add_column(
            sa.Column("acuity", sa.String(8), server_default="stable", nullable=False)
        )
        batch_op.add_column(sa.Column("label", sa.String(255), nullable=True))
        for name in ("treatment_changes", "physical_examination", "assessment", "clinical_summary"):
            batch_op.add_column(sa.Column(name, sa.Text(), server_default="", nullable=False))
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column("bucket", sa.String(10), server_default="today", nullable=False)
        )
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(
            sa.Column("schedule_type", sa.String(10), server_default="absolute", nullable=False)
        )
        batch_op.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fixed_time", sa.Time(), nullable=True))
        batch_op.add_column(sa.Column("anchor_at", sa.String(40), nullable=True))


def downgrade() -> None:
    """Remove Phase V metadata without affecting earlier schema fields."""
    with op.batch_alter_table("reminders") as batch_op:
        for name in ("anchor_at", "fixed_time", "interval_minutes", "schedule_type"):
            batch_op.drop_column(name)
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("bucket")
    with op.batch_alter_table("hospital_days") as batch_op:
        for name in (
            "clinical_summary",
            "assessment",
            "physical_examination",
            "treatment_changes",
            "label",
            "acuity",
        ):
            batch_op.drop_column(name)
    with op.batch_alter_table("patients") as batch_op:
        for name in ("active_order", "acuity", "blood_type", "code_status", "one_line_summary"):
            batch_op.drop_column(name)
