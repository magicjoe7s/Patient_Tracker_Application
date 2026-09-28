"""Add durable task lineage, occurrence, carry, and collection ordering.

Revision ID: 0002_task_lineage
Revises: 0001_initial_domain
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_task_lineage"
down_revision: str | None = "0001_initial_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve earlier tasks while introducing explicit occurrence metadata."""
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(
            sa.Column("ordering_position", sa.Integer(), server_default="0", nullable=False)
        )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("lineage_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("source_task_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("occurrence_number", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("carry_forward", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("ordering_position", sa.Integer(), server_default="0", nullable=False)
        )

    op.execute(sa.text("UPDATE tasks SET lineage_id = id WHERE lineage_id IS NULL"))

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.alter_column("lineage_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            "fk_task_source", "tasks", ["source_task_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_unique_constraint("uq_task_lineage_day", ["hospital_day_id", "lineage_id"])
        batch_op.alter_column("occurrence_number", server_default=None)
        batch_op.alter_column("carry_forward", server_default=None)
        batch_op.alter_column("ordering_position", server_default=None)

    with op.batch_alter_table("devices") as batch_op:
        batch_op.alter_column("ordering_position", server_default=None)


def downgrade() -> None:
    """Remove task-lineage metadata while leaving initial clinical records intact."""
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("uq_task_lineage_day", type_="unique")
        batch_op.drop_constraint("fk_task_source", type_="foreignkey")
        batch_op.drop_column("ordering_position")
        batch_op.drop_column("carry_forward")
        batch_op.drop_column("occurrence_number")
        batch_op.drop_column("source_task_id")
        batch_op.drop_column("lineage_id")
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("ordering_position")
