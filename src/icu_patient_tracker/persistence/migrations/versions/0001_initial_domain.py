"""Create the initial clinical domain schema.

Revision ID: 0001_initial_domain
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_domain"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all Phase III persistence tables before task-lineage metadata."""
    op.create_table(
        "patients",
        sa.Column("mrn", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("species", sa.String(128), nullable=False),
        sa.Column("breed", sa.String(128)),
        sa.Column("sex", sa.String(16), nullable=False),
        sa.Column("reproductive_status", sa.String(16), nullable=False),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column("estimated_age_years", sa.Float()),
        sa.Column("body_weight_kg", sa.Float()),
        sa.Column("admission_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "hospital_days",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "patient_mrn",
            sa.String(64),
            sa.ForeignKey("patients.mrn", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.String(40), nullable=False),
        sa.Column("end_at", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("patient_mrn", "calendar_date", name="uq_hospital_day_date"),
        sa.UniqueConstraint("patient_mrn", "day_number", name="uq_hospital_day_number"),
        sa.UniqueConstraint("id", "patient_mrn", name="uq_hospital_day_owner"),
    )
    op.create_table(
        "problem_lists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hospital_day_id",
            sa.Uuid(),
            sa.ForeignKey("hospital_days.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "problems",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "problem_list_id",
            sa.Uuid(),
            sa.ForeignKey("problem_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("identified_at", sa.String(40), nullable=False),
        sa.Column("resolved_at", sa.String(40)),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("ordering_position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("problem_list_id", "ordering_position", name="uq_problem_order"),
    )
    op.create_table(
        "instrumentations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hospital_day_id",
            sa.Uuid(),
            sa.ForeignKey("hospital_days.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrumentation_id",
            sa.Uuid(),
            sa.ForeignKey("instrumentations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_type", sa.String(32), nullable=False),
        sa.Column("anatomical_location", sa.String(255), nullable=False),
        sa.Column("placed_at", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("removed_at", sa.String(40)),
        sa.Column("size", sa.String(128)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("complications", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hospital_day_id",
            sa.Uuid(),
            sa.ForeignKey("hospital_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("due_at", sa.String(40)),
        sa.Column("completed_at", sa.String(40)),
        sa.Column("assigned_to", sa.String(255)),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("source", sa.String(255)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("trigger_at", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snoozed_until", sa.String(40)),
        sa.Column("dismissed_at", sa.String(40)),
        sa.Column("completed_at", sa.String(40)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "soap_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hospital_day_id",
            sa.Uuid(),
            sa.ForeignKey("hospital_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("update_type", sa.String(16), nullable=False),
        sa.Column("subjective", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "amends_document_id",
            sa.Uuid(),
            sa.ForeignKey("soap_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("finalized_at", sa.String(40)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "soap_problem_references",
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("soap_documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "problem_id",
            sa.Uuid(),
            sa.ForeignKey("problems.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordering_position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """Remove the empty initial schema in reverse dependency order."""
    op.drop_table("soap_problem_references")
    op.drop_table("soap_documents")
    op.drop_table("reminders")
    op.drop_table("tasks")
    op.drop_table("devices")
    op.drop_table("instrumentations")
    op.drop_table("problems")
    op.drop_table("problem_lists")
    op.drop_table("hospital_days")
    op.drop_table("patients")
