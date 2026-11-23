"""Separate staff acceptance from attendance and store private customer updates."""

import sqlalchemy as sa
from alembic import op

revision = "0011_booking_acceptance"
down_revision = "0010_booking_arrival"
branch_labels = None
depends_on = None
OLD_NOTICE = "(kind = 'booking_confirmed' AND reservation_id IS NOT NULL AND intent_key IS NULL) OR (kind = 'time_requested' AND reservation_id IS NULL AND intent_key IS NOT NULL AND client_id IS NOT NULL)"
NOTICE = OLD_NOTICE.replace(
    "kind = 'booking_confirmed'", "kind IN ('booking_confirmed', 'booking_requested')"
)


def detach_sqlite_notices():
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        return None
    # Rebuild dependent tables as well, keeping foreign-key enforcement enabled.
    # An explicit transaction also covers DDL under sqlite3's legacy transaction mode.
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    metadata = sa.MetaData()
    notices = sa.Table("staff_notifications", metadata, autoload_with=connection)
    reads = sa.Table("staff_notification_reads", metadata, autoload_with=connection)
    saved = (
        [dict(row) for row in connection.execute(sa.select(notices)).mappings()],
        [dict(row) for row in connection.execute(sa.select(reads)).mappings()],
    )
    op.drop_table("staff_notification_reads")
    op.drop_table("staff_notifications")
    return saved


def restore_sqlite_notices(saved, *, pending):
    if saved is None:
        return
    op.create_table(
        "staff_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("complex_id", sa.Uuid(), sa.ForeignKey("complexes.id"), nullable=False),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id"), nullable=True),
        sa.Column("intent_key", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("requested_day", sa.Date(), nullable=False),
        sa.Column("preferred_time", sa.String(5), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("reservation_id", name="uq_staff_notifications_reservation"),
        sa.UniqueConstraint("intent_key", name="uq_staff_notifications_intent"),
        sa.CheckConstraint("minutes IN (60, 90, 120)", name="ck_staff_notifications_duration"),
        sa.CheckConstraint(
            NOTICE if pending else OLD_NOTICE,
            name="ck_staff_notifications_kind",
        ),
    )
    op.create_index(
        "ix_staff_notifications_complex", "staff_notifications", ["complex_id", "created_at", "id"]
    )
    op.create_table(
        "staff_notification_reads",
        sa.Column(
            "notification_id", sa.Uuid(), sa.ForeignKey("staff_notifications.id"), primary_key=True
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("read_at", sa.DateTime(), nullable=False),
    )
    connection = op.get_bind()
    for name, rows in zip(("staff_notifications", "staff_notification_reads"), saved):
        if rows:
            table = sa.Table(name, sa.MetaData(), autoload_with=connection)
            connection.execute(table.insert(), rows)
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Arrival migration did not preserve notification references.")


def upgrade():
    saved = detach_sqlite_notices()
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(
            sa.Column("approval_status", sa.String(12), nullable=False, server_default="accepted")
        )
        batch.create_check_constraint(
            "ck_reservations_acceptance", "approval_status IN ('awaiting', 'accepted')"
        )
        batch.create_check_constraint(
            "ck_reservations_awaiting",
            "approval_status = 'accepted' OR (source = 'online' AND client_id IS NOT NULL AND arrived_at IS NULL)",
        )
    restore_sqlite_notices(saved, pending=True)
    op.create_table(
        "client_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("reservation_id", "kind", name="uq_client_notifications_event"),
        sa.CheckConstraint(
            "kind IN ('accepted', 'cancelled')", name="ck_client_notifications_kind"
        ),
    )
    op.create_index(
        "ix_client_notifications_owner", "client_notifications", ["client_id", "created_at", "id"]
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT COUNT(*) FROM reservations WHERE approval_status = 'awaiting'")
    ) or connection.scalar(sa.text("SELECT COUNT(*) FROM client_notifications")):
        raise RuntimeError(
            "Acceptance history exists; restore a compatible backup instead of dropping customer requests or updates."
        )
    op.drop_table("client_notifications")
    saved = detach_sqlite_notices()
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("ck_reservations_awaiting", type_="check")
        batch.drop_constraint("ck_reservations_acceptance", type_="check")
        batch.drop_column("approval_status")
    restore_sqlite_notices(saved, pending=True)
