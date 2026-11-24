"""Persist booking alerts, explicit time requests and each staff member's read state."""

import sqlalchemy as sa
from alembic import op

revision = "0007_staff_notifications"
down_revision = "0006_reservations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staff_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("complex_id", sa.Uuid(), nullable=False),
        sa.Column("facility_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("intent_key", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("requested_day", sa.Date(), nullable=False),
        sa.Column("preferred_time", sa.String(5), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_staff_notifications"),
        sa.ForeignKeyConstraint(
            ["complex_id"], ["complexes.id"], name="fk_staff_notifications_complex"
        ),
        sa.ForeignKeyConstraint(
            ["facility_id"], ["facilities.id"], name="fk_staff_notifications_facility"
        ),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], name="fk_staff_notifications_client"),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservations.id"], name="fk_staff_notifications_booking"
        ),
        sa.UniqueConstraint("reservation_id", name="uq_staff_notifications_reservation"),
        sa.UniqueConstraint("intent_key", name="uq_staff_notifications_intent"),
        sa.CheckConstraint("minutes IN (60, 90, 120)", name="ck_staff_notifications_duration"),
        sa.CheckConstraint(
            "(kind = 'booking_confirmed' AND reservation_id IS NOT NULL AND intent_key IS NULL) OR "
            "(kind = 'time_requested' AND reservation_id IS NULL AND intent_key IS NOT NULL)",
            name="ck_staff_notifications_kind",
        ),
    )
    op.create_index(
        "ix_staff_notifications_complex", "staff_notifications", ["complex_id", "created_at", "id"]
    )
    op.create_table(
        "staff_notification_reads",
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("notification_id", "user_id", name="pk_staff_notification_reads"),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["staff_notifications.id"],
            name="fk_staff_notification_reads_notice",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_staff_notification_reads_user"),
    )


def downgrade():
    op.drop_table("staff_notification_reads")
    op.drop_table("staff_notifications")
