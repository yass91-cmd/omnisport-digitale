"""Create complex, sport and facility ownership tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "complexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_complexes"),
    )
    op.create_index("ix_complexes_city", "complexes", ["city"])
    op.create_table(
        "sports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sports"),
        sa.UniqueConstraint("slug", name="uq_sports_slug"),
    )
    op.create_table(
        "facilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("complex_id", sa.Uuid(), nullable=False),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("surface", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(
            ["complex_id"], ["complexes.id"], name="fk_facilities_complex_id_complexes"
        ),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"], name="fk_facilities_sport_id_sports"),
        sa.PrimaryKeyConstraint("id", name="pk_facilities"),
        sa.UniqueConstraint("complex_id", "name", name="uq_facilities_complex_name"),
    )
    op.create_index("ix_facilities_complex_id", "facilities", ["complex_id"])
    op.create_index("ix_facilities_sport_id", "facilities", ["sport_id"])


def downgrade():
    op.drop_table("facilities")
    op.drop_table("sports")
    op.drop_table("complexes")
