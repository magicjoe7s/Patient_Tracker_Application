"""Add durable problem lineage and occurrence metadata.

Revision ID: 0006_problem_lineage
Revises: 0005_chronological_day_numbers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_problem_lineage"
down_revision: str | None = "0005_chronological_day_numbers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve existing problems as the first occurrence in their own lineage."""
    with op.batch_alter_table("problems") as batch_op:
        batch_op.add_column(sa.Column("lineage_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("source_problem_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("occurrence_number", sa.Integer(), server_default="1", nullable=False)
        )

    op.execute(sa.text("UPDATE problems SET lineage_id = id WHERE lineage_id IS NULL"))

    with op.batch_alter_table("problems") as batch_op:
        batch_op.alter_column("lineage_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            "fk_problem_source",
            "problems",
            ["source_problem_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_problem_lineage_day", ["problem_list_id", "lineage_id"]
        )
        batch_op.alter_column("occurrence_number", server_default=None)


def downgrade() -> None:
    """Remove problem lineage metadata while retaining each problem occurrence."""
    with op.batch_alter_table("problems") as batch_op:
        batch_op.drop_constraint("uq_problem_lineage_day", type_="unique")
        batch_op.drop_constraint("fk_problem_source", type_="foreignkey")
        batch_op.drop_column("occurrence_number")
        batch_op.drop_column("source_problem_id")
        batch_op.drop_column("lineage_id")
