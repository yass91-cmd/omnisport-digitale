"""Add accounts, complex-scoped staff, revocable sessions and attempt counters."""

import sqlalchemy as sa
from alembic import op

revision = "0002_accounts"
down_revision = "0001_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("client_role", sa.String(16), server_default="player", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("client_role IN ('player', 'coach')", name="ck_users_client_role"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "staff_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("complex_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint("role IN ('employee', 'admin')", name="ck_staff_assignments_role"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_staff_assignments_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["complex_id"], ["complexes.id"], name="fk_staff_assignments_complex_id_complexes"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_assignments"),
        sa.UniqueConstraint("user_id", "complex_id", name="uq_staff_assignments_user_complex"),
    )
    op.create_index("ix_staff_assignments_user_id", "staff_assignments", ["user_id"])
    op.create_index("ix_staff_assignments_complex_id", "staff_assignments", ["complex_id"])
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_login_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("token_hash", name="pk_login_sessions"),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table(
        "auth_attempt_buckets",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_auth_attempt_buckets"),
    )
    op.create_index("ix_auth_attempt_buckets_expires_at", "auth_attempt_buckets", ["expires_at"])


def downgrade():
    op.drop_table("auth_attempt_buckets")
    op.drop_table("login_sessions")
    op.drop_table("staff_assignments")
    op.drop_table("users")
