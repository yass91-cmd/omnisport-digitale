"""Add bounded weekend and evening increases without replacing facility data."""

import sqlalchemy as sa
from alembic import op

revision = "0004_peak_pricing"
down_revision = "0003_facility_settings"
branch_labels = None
depends_on = None


def upgrade():
    for name in ["weekend_percent", "evening_percent"]:
        constraint = f"ck_facilities_{name}"
        condition = f"{name} >= 0 AND {name} <= 100"
        if op.get_bind().dialect.name == "sqlite":
            # SQLite can add a column with its own check without copying the
            # referenced parent table, preserving existing hours and tariffs.
            op.execute(
                f"ALTER TABLE facilities ADD COLUMN {name} NUMERIC(5, 2) NOT NULL DEFAULT 10.00 CONSTRAINT {constraint} CHECK ({condition})"
            )
        else:
            op.add_column(
                "facilities",
                sa.Column(name, sa.Numeric(5, 2), nullable=False, server_default="10.00"),
            )
            op.create_check_constraint(constraint, "facilities", condition)


def downgrade():
    for name in ["evening_percent", "weekend_percent"]:
        if op.get_bind().dialect.name != "sqlite":
            op.drop_constraint(f"ck_facilities_{name}", "facilities", type_="check")
        op.drop_column("facilities", name)
