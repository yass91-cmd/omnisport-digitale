"""Persist booking events before publishing them to Kafka."""

import sqlalchemy as sa
from alembic import op

revision = "0015_booking_event_outbox"
down_revision = "0014_maintenance_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(249), nullable=False),
        sa.Column("message_key", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("schema_version >= 1", name="ck_outbox_events_schema_version"),
    )
    op.create_index(
        "ix_outbox_events_pending", "outbox_events", ["published_at", "created_at", "id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM outbox_events")):
        raise RuntimeError("Booking event history exists; review it before downgrade.")
    op.drop_table("outbox_events")
