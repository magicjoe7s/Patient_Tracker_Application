"""Replace MRN ownership with generated patient UUID identity.

Revision ID: 0004_patient_uuid_identity
Revises: 0003_application_services
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0004_patient_uuid_identity"
down_revision: str | None = "0003_application_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PATIENT_COLUMNS = (
    "name, species, breed, sex, reproductive_status, date_of_birth, "
    "estimated_age_years, body_weight_kg, admission_status, created_at, updated_at, "
    "one_line_summary, code_status, blood_type, acuity, active_order"
)

DAY_COLUMNS = (
    "id, calendar_date, day_number, start_at, end_at, status, created_at, updated_at, "
    "acuity, label, treatment_changes, physical_examination, assessment, clinical_summary"
)

QUALIFIED_DAY_COLUMNS = (
    "hospital_days.id, hospital_days.calendar_date, hospital_days.day_number, "
    "hospital_days.start_at, hospital_days.end_at, hospital_days.status, "
    "hospital_days.created_at, hospital_days.updated_at, hospital_days.acuity, "
    "hospital_days.label, hospital_days.treatment_changes, "
    "hospital_days.physical_examination, hospital_days.assessment, "
    "hospital_days.clinical_summary"
)


def _create_uuid_tables() -> None:
    op.create_table(
        "patients_uuid",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mrn", sa.String(64), nullable=True, unique=True),
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
        sa.Column("one_line_summary", sa.Text(), nullable=False),
        sa.Column("code_status", sa.String(18), nullable=False),
        sa.Column("blood_type", sa.String(64)),
        sa.Column("acuity", sa.String(8), nullable=False),
        sa.Column("active_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "hospital_days_uuid",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(),
            sa.ForeignKey("patients_uuid.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.String(40), nullable=False),
        sa.Column("end_at", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("acuity", sa.String(8), nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("treatment_changes", sa.Text(), nullable=False),
        sa.Column("physical_examination", sa.Text(), nullable=False),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("clinical_summary", sa.Text(), nullable=False),
        sa.UniqueConstraint("patient_id", "calendar_date", name="uq_hospital_day_date"),
        sa.UniqueConstraint("patient_id", "day_number", name="uq_hospital_day_number"),
        sa.UniqueConstraint("id", "patient_id", name="uq_hospital_day_owner"),
    )


def upgrade() -> None:
    """Generate patient UUIDs and redirect hospital-day ownership without data loss."""
    connection = op.get_bind()
    _create_uuid_tables()
    mrns = tuple(connection.execute(sa.text("SELECT mrn FROM patients")).scalars())
    patient_ids = {mrn: uuid4().hex for mrn in mrns}
    for mrn, patient_id in patient_ids.items():
        connection.execute(
            sa.text(
                f"INSERT INTO patients_uuid (id, mrn, {PATIENT_COLUMNS}) "
                f"SELECT :patient_id, mrn, {PATIENT_COLUMNS} FROM patients WHERE mrn = :mrn"
            ),
            {"patient_id": patient_id, "mrn": mrn},
        )
        connection.execute(
            sa.text(
                f"INSERT INTO hospital_days_uuid ({DAY_COLUMNS}, patient_id) "
                f"SELECT {DAY_COLUMNS}, :patient_id FROM hospital_days WHERE patient_mrn = :mrn"
            ),
            {"patient_id": patient_id, "mrn": mrn},
        )
    op.drop_table("hospital_days")
    op.drop_table("patients")
    op.rename_table("patients_uuid", "patients")
    op.rename_table("hospital_days_uuid", "hospital_days")


def downgrade() -> None:
    """Restore MRN ownership only when every patient still has a unique MRN."""
    connection = op.get_bind()
    missing = connection.scalar(sa.text("SELECT COUNT(*) FROM patients WHERE mrn IS NULL"))
    if missing:
        raise RuntimeError("Cannot downgrade UUID identity while patients without MRNs exist.")

    op.create_table(
        "patients_mrn",
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
        sa.Column("one_line_summary", sa.Text(), nullable=False),
        sa.Column("code_status", sa.String(18), nullable=False),
        sa.Column("blood_type", sa.String(64)),
        sa.Column("acuity", sa.String(8), nullable=False),
        sa.Column("active_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "hospital_days_mrn",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "patient_mrn",
            sa.String(64),
            sa.ForeignKey("patients_mrn.mrn", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.String(40), nullable=False),
        sa.Column("end_at", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("acuity", sa.String(8), nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("treatment_changes", sa.Text(), nullable=False),
        sa.Column("physical_examination", sa.Text(), nullable=False),
        sa.Column("assessment", sa.Text(), nullable=False),
        sa.Column("clinical_summary", sa.Text(), nullable=False),
        sa.UniqueConstraint("patient_mrn", "calendar_date", name="uq_hospital_day_date"),
        sa.UniqueConstraint("patient_mrn", "day_number", name="uq_hospital_day_number"),
        sa.UniqueConstraint("id", "patient_mrn", name="uq_hospital_day_owner"),
    )
    connection.execute(
        sa.text(
            f"INSERT INTO patients_mrn (mrn, {PATIENT_COLUMNS}) "
            f"SELECT mrn, {PATIENT_COLUMNS} FROM patients"
        )
    )
    connection.execute(
        sa.text(
            f"INSERT INTO hospital_days_mrn ({DAY_COLUMNS}, patient_mrn) "
            f"SELECT {QUALIFIED_DAY_COLUMNS}, patients.mrn FROM hospital_days "
            "JOIN patients ON patients.id = hospital_days.patient_id"
        )
    )
    op.drop_table("hospital_days")
    op.drop_table("patients")
    op.rename_table("patients_mrn", "patients")
    op.rename_table("hospital_days_mrn", "hospital_days")
