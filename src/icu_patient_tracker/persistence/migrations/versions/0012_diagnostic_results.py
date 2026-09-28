"""Add structured results linked one-to-one with diagnostic tasks.

Revision ID: 0012_diagnostic_results
Revises: 0011_legacy_import_audit
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012_diagnostic_results"
down_revision: str | None = "0011_legacy_import_audit"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create task-owned diagnostic result storage."""
    op.create_table(
        "diagnostic_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )


def downgrade() -> None:
    """Remove diagnostic results without changing their owning tasks."""
    op.drop_table("diagnostic_results")
