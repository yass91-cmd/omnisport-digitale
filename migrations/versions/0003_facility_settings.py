"""Add weekly opening intervals, sport durations and facility tariffs."""

import sqlalchemy as sa
from alembic import op

revision = "0003_facility_settings"
down_revision = "0002_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "complexes", sa.Column("currency", sa.String(3), nullable=False, server_default="MAD")
    )
    with op.batch_alter_table("facilities") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_unique_constraint("uq_facilities_id_sport", ["id", "sport_id"])
        batch.create_check_constraint("ck_facilities_version", "version >= 1")
    op.create_table(
        "sport_durations",
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("sport_id", "minutes", name="pk_sport_durations"),
        sa.ForeignKeyConstraint(
            ["sport_id"], ["sports.id"], name="fk_sport_durations_sport_id_sports"
        ),
        sa.CheckConstraint("minutes > 0 AND minutes <= 1440", name="ck_sport_durations_minutes"),
    )
    durations = sa.table(
        "sport_durations", sa.column("sport_id", sa.Uuid()), sa.column("minutes", sa.Integer())
    )
    sports = sa.table("sports", sa.column("id", sa.Uuid()))
    connection = op.get_bind()
    for sport_id in connection.execute(sa.select(sports.c.id)).scalars():
        connection.execute(
            sa.insert(durations),
            [{"sport_id": sport_id, "minutes": value} for value in [60, 90, 120]],
        )
    op.create_table(
        "opening_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("facility_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_opening_hours"),
        sa.ForeignKeyConstraint(
            ["facility_id"], ["facilities.id"], name="fk_opening_hours_facility_id_facilities"
        ),
        sa.UniqueConstraint(
            "facility_id", "weekday", "start_minute", name="uq_opening_hours_start"
        ),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_opening_hours_weekday"),
        sa.CheckConstraint(
            "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440",
            name="ck_opening_hours_interval",
        ),
    )
    op.create_index("ix_opening_hours_facility_id", "opening_hours", ["facility_id"])
    op.create_table(
        "facility_tariffs",
        sa.Column("facility_id", sa.Uuid(), nullable=False),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.PrimaryKeyConstraint("facility_id", "minutes", name="pk_facility_tariffs"),
        sa.ForeignKeyConstraint(
            ["facility_id", "sport_id"],
            ["facilities.id", "facilities.sport_id"],
            name="fk_facility_tariffs_owner_sport",
        ),
        sa.ForeignKeyConstraint(
            ["sport_id", "minutes"],
            ["sport_durations.sport_id", "sport_durations.minutes"],
            name="fk_facility_tariffs_allowed_duration",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_facility_tariffs_amount"),
    )


def downgrade():
    op.drop_table("facility_tariffs")
    op.drop_table("opening_hours")
    op.drop_table("sport_durations")
    with op.batch_alter_table("facilities") as batch:
        batch.drop_constraint("ck_facilities_version", type_="check")
        batch.drop_constraint("uq_facilities_id_sport", type_="unique")
        batch.drop_column("version")
    op.drop_column("complexes", "currency")
