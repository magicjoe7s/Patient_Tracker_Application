"""Normalize hospital-day numbers to chronological ICU ordinals.

Revision ID: 0005_chronological_day_numbers
Revises: 0004_patient_uuid_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_chronological_day_numbers"
down_revision: str | None = "0004_patient_uuid_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Renumber each patient's days by calendar date without violating uniqueness."""
    connection = op.get_bind()
    patient_ids: tuple[str, ...] = tuple(
        connection.execute(sa.text("SELECT id FROM patients ORDER BY id")).scalars()
    )
    for patient_id in patient_ids:
        day_ids: tuple[str, ...] = tuple(
            connection.execute(
                sa.text(
                    "SELECT id FROM hospital_days WHERE patient_id = :patient_id "
                    "ORDER BY calendar_date, start_at, id"
                ),
                {"patient_id": patient_id},
            ).scalars()
        )
        for temporary_number, day_id in enumerate(day_ids, start=1):
            connection.execute(
                sa.text("UPDATE hospital_days SET day_number = :day_number WHERE id = :day_id"),
                {"day_number": -temporary_number, "day_id": day_id},
            )
        for day_number, day_id in enumerate(day_ids, start=1):
            connection.execute(
                sa.text("UPDATE hospital_days SET day_number = :day_number WHERE id = :day_id"),
                {"day_number": day_number, "day_id": day_id},
            )


def downgrade() -> None:
    """Retain safe chronological numbering because prior creation order is not stored."""
