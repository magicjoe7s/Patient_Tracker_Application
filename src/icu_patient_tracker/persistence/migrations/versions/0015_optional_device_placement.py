"""Allow unknown device placement dates without inventing clinical timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "0015_optional_device_placement"
down_revision = "0014_clinical_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("placed_at", existing_type=sa.String(40), nullable=True)


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM devices WHERE placed_at IS NULL"))
    if count:
        raise ValueError(
            "Cannot downgrade while devices have unknown placement dates. "
            "Record their actual placement dates before downgrading."
        )
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("placed_at", existing_type=sa.String(40), nullable=False)
