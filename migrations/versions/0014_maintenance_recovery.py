"""Audit maintenance resolutions and allow rescheduling updates."""

import sqlalchemy as sa
from alembic import op

revision = "0014_maintenance_recovery"
down_revision = "0013_team_contacts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("client_notifications") as batch:
        batch.drop_constraint("ck_client_notifications_kind", type_="check")
        batch.create_check_constraint(
            "ck_client_notifications_kind", "kind IN ('accepted', 'cancelled', 'rescheduled')"
        )
    op.create_table(
        "maintenance_changes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("closure_id", sa.Uuid(), sa.ForeignKey("facility_closures.id"), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("old_start", sa.DateTime(), nullable=False),
        sa.Column("old_end", sa.DateTime(), nullable=False),
        sa.Column("new_start", sa.DateTime(), nullable=True),
        sa.Column("new_end", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_maintenance_changes_reservation_id", "maintenance_changes", ["reservation_id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM maintenance_changes")):
        raise RuntimeError("Maintenance history exists; review before downgrade.")
    op.drop_table("maintenance_changes")
    with op.batch_alter_table("client_notifications") as batch:
        batch.drop_constraint("ck_client_notifications_kind", type_="check")
        batch.create_check_constraint(
            "ck_client_notifications_kind", "kind IN ('accepted', 'cancelled')"
        )
