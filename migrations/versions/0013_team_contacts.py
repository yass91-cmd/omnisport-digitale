"""Store coach-entered players without creating login accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0013_team_contacts"
down_revision = "0012_teams"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("roster_identity_locks", sa.Column("key", sa.String(64), primary_key=True))
    op.create_table(
        "team_contact_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("sport_id", sa.Uuid(), sa.ForeignKey("sports.id"), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "identity_key", "sport_id", "active_slot", name="uq_contact_member_sport"
        ),
        sa.CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_at IS NULL) OR (active_slot IS NULL AND ended_at IS NOT NULL)",
            name="ck_contact_member_state",
        ),
    )
    op.create_index("ix_team_contact_members_team_id", "team_contact_members", ["team_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM team_contact_members")):
        raise RuntimeError("Player contact history exists; export and review it before downgrade.")
    op.drop_table("team_contact_members")
    op.drop_table("roster_identity_locks")
