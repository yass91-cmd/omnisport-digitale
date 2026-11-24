"""Add dated facility closures without altering saved hours, prices or accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0005_availability_closures"
down_revision = "0004_peak_pricing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "facility_closures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("facility_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_facility_closures"),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"], name="fk_closures_facility"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_closures_creator"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], name="fk_closures_canceller"),
        sa.CheckConstraint("starts_at < ends_at", name="ck_facility_closures_interval"),
        sa.CheckConstraint(
            "(active = 1 AND cancelled_at IS NULL AND cancelled_by IS NULL) OR "
            "(active = 0 AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
            name="ck_facility_closures_cancellation",
        ),
    )
    op.create_index(
        "ix_facility_closures_schedule",
        "facility_closures",
        ["facility_id", "active", "ends_at", "starts_at"],
    )


def downgrade():
    op.drop_table("facility_closures")
