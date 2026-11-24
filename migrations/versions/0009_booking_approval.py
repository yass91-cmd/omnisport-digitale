"""Hold online requests until assigned staff approve; preserve existing bookings."""

import sqlalchemy as sa
from alembic import op

revision = "0009_booking_approval"
down_revision = "0008_booking_contacts"
branch_labels = None
depends_on = None

OLD_NOTICE = "(kind = 'booking_confirmed' AND reservation_id IS NOT NULL AND intent_key IS NULL) OR (kind = 'time_requested' AND reservation_id IS NULL AND intent_key IS NOT NULL AND client_id IS NOT NULL)"
NOTICE = OLD_NOTICE.replace(
    "kind = 'booking_confirmed'", "kind IN ('booking_confirmed', 'booking_requested')"
)
APPROVAL = "(approved_at IS NULL AND approved_by IS NULL) OR (approved_at IS NOT NULL AND approved_by IS NOT NULL AND source = 'online' AND status IN ('confirmed', 'cancelled'))"


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
        raise RuntimeError("Contact migration did not preserve notification references.")


def change_checks(batch, *, pending):
    batch.drop_constraint("ck_reservations_status", type_="check")
    batch.create_check_constraint(
        "ck_reservations_status",
        "status IN ('pending', 'confirmed', 'cancelled')"
        if pending
        else "status IN ('confirmed', 'cancelled')",
    )
    batch.drop_constraint("ck_reservations_cancellation", type_="check")
    batch.create_check_constraint(
        "ck_reservations_cancellation",
        ("(status IN ('pending', 'confirmed')" if pending else "(status = 'confirmed'")
        + " AND cancelled_at IS NULL AND cancelled_by IS NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL)",
    )


def change_notice(saved, *, pending):
    if saved is None:
        with op.batch_alter_table("staff_notifications") as batch:
            batch.drop_constraint("ck_staff_notifications_kind", type_="check")
            batch.create_check_constraint(
                "ck_staff_notifications_kind", NOTICE if pending else OLD_NOTICE
            )
    restore_sqlite_notices(saved, pending=pending)


def upgrade():
    saved = detach_sqlite_notices()
    with op.batch_alter_table("reservations") as batch:
        batch.add_column(sa.Column("approved_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_reservations_approver", "users", ["approved_by"], ["id"])
        batch.create_check_constraint("ck_reservations_approval", APPROVAL)
        change_checks(batch, pending=True)
    change_notice(saved, pending=True)


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM reservations WHERE status = 'pending' OR approved_at IS NOT NULL"
        )
    ) or connection.scalar(
        sa.text("SELECT COUNT(*) FROM staff_notifications WHERE kind = 'booking_requested'")
    ):
        raise RuntimeError(
            "Approval history exists; restore a compatible backup instead of dropping booking decisions."
        )
    saved = detach_sqlite_notices()
    with op.batch_alter_table("reservations") as batch:
        change_checks(batch, pending=False)
        batch.drop_constraint("ck_reservations_approval", type_="check")
        batch.drop_constraint("fk_reservations_approver", type_="foreignkey")
        batch.drop_column("approved_by")
        batch.drop_column("approved_at")
    change_notice(saved, pending=False)
