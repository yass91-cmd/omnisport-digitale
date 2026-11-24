"""Store confirmed bookings, price snapshots and cancellation audit."""

import sqlalchemy as sa
from alembic import op

revision = "0006_reservations"
down_revision = "0005_availability_closures"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column(name, sa.Uuid(), nullable=False)
        for name in ["id", "request_id", "facility_id", "client_id", "entered_by"]
    ]
    columns += [
        sa.Column("reference", sa.String(24), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    ]
    columns += [
        sa.Column(name, sa.DateTime(), nullable=False)
        for name in ["starts_at", "ends_at", "created_at"]
    ]
    columns += [
        sa.Column(name, sa.Integer(), nullable=False) for name in ["minutes", "quoted_version"]
    ]
    columns += [
        sa.Column("base_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("applied_percent", sa.Numeric(5, 2), nullable=False),
    ]
    columns += [
        sa.Column(name, sa.Boolean(), nullable=False)
        for name in ["weekend_applied", "evening_applied"]
    ]
    op.create_table(
        "reservations",
        *columns,
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(12), nullable=False, server_default="confirmed"),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_reservations"),
        sa.UniqueConstraint("reference", name="uq_reservations_reference"),
        sa.UniqueConstraint("entered_by", "request_id", name="uq_reservations_request"),
        sa.ForeignKeyConstraint(
            ["facility_id"], ["facilities.id"], name="fk_reservations_facility"
        ),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], name="fk_reservations_client"),
        sa.ForeignKeyConstraint(["entered_by"], ["users.id"], name="fk_reservations_actor"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], name="fk_reservations_canceller"),
        sa.CheckConstraint("starts_at < ends_at", name="ck_reservations_interval"),
        sa.CheckConstraint("minutes IN (60, 90, 120)", name="ck_reservations_duration"),
        sa.CheckConstraint("version >= 1 AND quoted_version >= 1", name="ck_reservations_versions"),
        sa.CheckConstraint(
            "base_amount >= 0 AND total_amount >= base_amount", name="ck_reservations_price"
        ),
        sa.CheckConstraint(
            "applied_percent >= 0 AND applied_percent <= 200", name="ck_reservations_percent"
        ),
        sa.CheckConstraint("status IN ('confirmed', 'cancelled')", name="ck_reservations_status"),
        sa.CheckConstraint(
            "source IN ('online', 'staff') AND (source != 'online' OR client_id = entered_by)",
            name="ck_reservations_source",
        ),
        sa.CheckConstraint(
            "(status = 'confirmed' AND cancelled_at IS NULL AND cancelled_by IS NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
            name="ck_reservations_cancellation",
        ),
    )
    op.create_index(
        "ix_reservations_schedule",
        "reservations",
        ["facility_id", "status", "ends_at", "starts_at"],
    )
    op.create_index("ix_reservations_client", "reservations", ["client_id", "starts_at"])


def downgrade():
    op.drop_table("reservations")
