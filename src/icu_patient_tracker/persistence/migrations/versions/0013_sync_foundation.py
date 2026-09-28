"""Add local record-level synchronization foundation.

Revision ID: 0013_sync_foundation
Revises: 0012_diagnostic_results
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013_sync_foundation"
down_revision: str | None = "0012_diagnostic_results"
branch_labels: str | None = None
depends_on: str | None = None

SYNC_TRACKED_TABLES = (
    "patients",
    "hospital_days",
    "problem_lists",
    "problems",
    "instrumentations",
    "devices",
    "tasks",
    "diagnostic_results",
    "reminders",
    "soap_documents",
)


def upgrade() -> None:
    """Add reconciliation metadata, device state, outbox, and conflict storage."""
    for table_name in SYNC_TRACKED_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column("server_version", sa.Integer(), server_default="0", nullable=False)
            )
            batch_op.add_column(sa.Column("deleted_at", sa.String(length=40), nullable=True))

    op.create_table(
        "sync_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("last_pull_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("last_seen_at", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_outbox",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("base_server_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(
        "ix_sync_outbox_due", "sync_outbox", ["next_attempt_at", "created_at"], unique=False
    )
    op.create_table(
        "sync_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("local_payload_json", sa.Text(), nullable=False),
        sa.Column("server_payload_json", sa.Text(), nullable=False),
        sa.Column("server_version", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.String(length=40), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolved_at", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["sync_outbox.operation_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id"),
    )
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("last_push_at", sa.String(length=40), nullable=True),
        sa.Column("last_pull_at", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_sync_state_singleton"),
        sa.ForeignKeyConstraint(["device_id"], ["sync_devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )


def downgrade() -> None:
    """Remove all local sync state without changing clinical content."""
    op.drop_table("sync_state")
    op.drop_table("sync_conflicts")
    op.drop_index("ix_sync_outbox_due", table_name="sync_outbox")
    op.drop_table("sync_outbox")
    op.drop_table("sync_devices")
    for table_name in reversed(SYNC_TRACKED_TABLES):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("deleted_at")
            batch_op.drop_column("server_version")
