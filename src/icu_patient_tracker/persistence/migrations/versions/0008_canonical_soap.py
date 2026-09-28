"""Add lossless SOAP Markdown and day-owned staff attribution."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_canonical_soap"
down_revision: str | None = "0007_reminder_shown_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add conservative empty defaults without interpreting existing section text."""
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.add_column(
            sa.Column("overnight_resident", sa.String(255), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("faculty", sa.String(255), nullable=False, server_default=""))
    with op.batch_alter_table("soap_documents") as batch_op:
        batch_op.add_column(
            sa.Column("markdown_text", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Remove only Slice 8 columns."""
    with op.batch_alter_table("soap_documents") as batch_op:
        batch_op.drop_column("markdown_text")
    with op.batch_alter_table("hospital_days") as batch_op:
        batch_op.drop_column("faculty")
        batch_op.drop_column("overnight_resident")
