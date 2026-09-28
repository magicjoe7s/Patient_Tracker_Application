"""Durable patient snapshot revisions independent of patient graph replacement."""

import sqlalchemy as sa
from alembic import op

revision = "0014_clinical_sync"
down_revision = "0013_sync_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_sync",
        sa.Column("patient_id", sa.Uuid(), primary_key=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("local_revision", sa.Integer(), nullable=False),
        sa.Column("synced_revision", sa.Integer(), nullable=False),
        sa.Column("server_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("operation_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("clinical_sync")
