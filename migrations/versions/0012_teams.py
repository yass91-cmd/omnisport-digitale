"""Coach teams, membership history, consent requests and team booking labels."""

import sqlalchemy as sa
from alembic import op

revision = "0012_teams"
down_revision = "0011_booking_acceptance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("coach_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sport_id", sa.Uuid(), sa.ForeignKey("sports.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("open_to_requests", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("coach_id", "sport_id", "name", name="uq_teams_coach_sport_name"),
    )
    op.create_index("ix_teams_coach_id", "teams", ["coach_id"])
    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sport_id", sa.Uuid(), sa.ForeignKey("sports.id"), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "player_id", "sport_id", "active_slot", name="uq_membership_active_sport"
        ),
        sa.CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_at IS NULL) OR (active_slot IS NULL AND ended_at IS NOT NULL)",
            name="ck_membership_state",
        ),
    )
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"])
    op.create_index("ix_team_memberships_player_id", "team_memberships", ["player_id"])
    op.create_table(
        "team_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("pending_slot", sa.Integer(), nullable=True),
        sa.Column(
            "previous_membership_id", sa.Uuid(), sa.ForeignKey("team_memberships.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("team_id", "player_id", "pending_slot", name="uq_team_request_pending"),
        sa.CheckConstraint("kind IN ('join', 'invite')", name="ck_team_request_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn')",
            name="ck_team_request_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND pending_slot IS NOT NULL AND pending_slot = 1 AND decided_at IS NULL) OR (status <> 'pending' AND pending_slot IS NULL AND decided_at IS NOT NULL)",
            name="ck_team_request_state",
        ),
    )
    op.create_index("ix_team_requests_team_id", "team_requests", ["team_id"])
    op.create_index("ix_team_requests_player_id", "team_requests", ["player_id"])
    op.create_table(
        "team_bookings",
        sa.Column("reservation_id", sa.Uuid(), sa.ForeignKey("reservations.id"), primary_key=True),
        sa.Column("team_id", sa.Uuid(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("team_name", sa.String(100), nullable=False),
    )
    op.create_index("ix_team_bookings_team_id", "team_bookings", ["team_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM teams")):
        raise RuntimeError(
            "Team history exists; export and review it before removing this feature."
        )
    for table in ("team_bookings", "team_requests", "team_memberships", "teams"):
        op.drop_table(table)
