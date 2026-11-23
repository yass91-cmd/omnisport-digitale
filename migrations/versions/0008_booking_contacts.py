"""Store contact snapshots and support staff-entered walk-in reservations."""

import sqlalchemy as sa
from alembic import op

revision = "0008_booking_contacts"
down_revision = "0007_staff_notifications"
branch_labels = None
depends_on = None

SOURCE = (
    "source = 'staff' OR (source = 'online' AND client_id IS NOT NULL AND client_id = entered_by)"
)
NOTICE = "(kind = 'booking_confirmed' AND reservation_id IS NOT NULL AND intent_key IS NULL) OR (kind = 'time_requested' AND reservation_id IS NULL AND intent_key IS NOT NULL AND client_id IS NOT NULL)"


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


def restore_sqlite_notices(saved, *, contacts):
    if saved is None:
        return
    op.create_table(
        "staff_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("complex_id", sa.Uuid(), sa.ForeignKey("complexes.id"), nullable=False),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=contacts),
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
            NOTICE if contacts else NOTICE.replace(" AND client_id IS NOT NULL", ""),
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


def upgrade():
    saved = detach_sqlite_notices()
    op.add_column("users", sa.Column("phone", sa.String(20), nullable=True))
    op.create_index("ix_users_phone", "users", ["phone"])
    op.add_column("reservations", sa.Column("client_name", sa.String(100), nullable=True))
    op.add_column("reservations", sa.Column("client_phone", sa.String(20), nullable=True))
    op.execute(
        sa.text(
            "UPDATE reservations SET client_name = (SELECT users.name FROM users WHERE users.id = reservations.client_id)"
        )
    )
    with op.batch_alter_table("reservations") as batch:
        batch.alter_column("client_name", existing_type=sa.String(100), nullable=False)
        batch.alter_column("client_id", existing_type=sa.Uuid(), nullable=True)
        batch.drop_constraint("ck_reservations_source", type_="check")
        batch.create_check_constraint("ck_reservations_source", SOURCE)
    if saved is None:
        with op.batch_alter_table("staff_notifications") as batch:
            batch.alter_column("client_id", existing_type=sa.Uuid(), nullable=True)
            batch.drop_constraint("ck_staff_notifications_kind", type_="check")
            batch.create_check_constraint("ck_staff_notifications_kind", NOTICE)
    restore_sqlite_notices(saved, contacts=True)


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM reservations WHERE client_id IS NULL")):
        raise RuntimeError(
            "Walk-in booking history exists; restore a compatible backup instead of dropping its contact data."
        )
    saved = detach_sqlite_notices()
    if saved is None:
        with op.batch_alter_table("staff_notifications") as batch:
            batch.drop_constraint("ck_staff_notifications_kind", type_="check")
            batch.create_check_constraint(
                "ck_staff_notifications_kind", NOTICE.replace(" AND client_id IS NOT NULL", "")
            )
            batch.alter_column("client_id", existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table("reservations") as batch:
        batch.drop_constraint("ck_reservations_source", type_="check")
        batch.create_check_constraint(
            "ck_reservations_source",
            "source IN ('online', 'staff') AND (source != 'online' OR client_id = entered_by)",
        )
        batch.alter_column("client_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("client_phone")
        batch.drop_column("client_name")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "phone")
    restore_sqlite_notices(saved, contacts=False)
