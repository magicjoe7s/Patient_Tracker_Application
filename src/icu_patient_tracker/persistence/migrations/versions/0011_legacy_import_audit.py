"""Record immutable, non-clinical legacy-import provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_legacy_import_audit"
down_revision: str | None = "0010_emr_upload_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add one import-run audit row and hashed source-to-target identities."""
    op.create_table(
        "legacy_import_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("main_sha256", sa.String(64), nullable=False),
        sa.Column("archive_sha256", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.String(40), nullable=False),
        sa.Column("patient_count", sa.Integer(), nullable=False),
        sa.Column("day_count", sa.Integer(), nullable=False),
        sa.Column("task_count", sa.Integer(), nullable=False),
        sa.Column("problem_count", sa.Integer(), nullable=False),
        sa.Column("soap_count", sa.Integer(), nullable=False),
        sa.Column("device_count", sa.Integer(), nullable=False),
        sa.Column("reminder_count", sa.Integer(), nullable=False),
        sa.Column("setting_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("main_sha256", "archive_sha256", name="uq_legacy_import_source"),
    )
    op.create_table(
        "legacy_identity_map",
        sa.Column(
            "import_run_id",
            sa.String(32),
            sa.ForeignKey("legacy_import_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("entity_type", sa.String(16), primary_key=True),
        sa.Column("legacy_identity_sha256", sa.String(64), primary_key=True),
        sa.Column("target_uuid", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    """Remove legacy-import audit data without touching clinical aggregates."""
    op.drop_table("legacy_identity_map")
    op.drop_table("legacy_import_runs")
