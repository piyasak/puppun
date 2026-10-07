"""P2.5: Agent installations and sessions (fencing by generation).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _ts(name, nullable=False, default=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    op.create_table(
        "agent_installations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_id", sa.String(64), nullable=False),
        sa.Column("agent_version", sa.String(32), nullable=True),
        sa.Column("last_token_id", sa.Uuid(), sa.ForeignKey("agent_tokens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        _ts("created_at", default=True),
        _ts("last_seen_at", nullable=True),
        _ts("deregistered_at", nullable=True),
        sa.UniqueConstraint("environment_id", "installation_id"),
    )
    op.create_index("ix_agent_installations_workspace_id", "agent_installations", ["workspace_id"])
    op.create_index("ix_agent_installations_environment_id", "agent_installations", ["environment_id"])

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_ref", sa.Uuid(), sa.ForeignKey("agent_installations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token_id", sa.Uuid(), sa.ForeignKey("agent_tokens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        _ts("created_at", default=True),
        _ts("last_heartbeat_at"),
        _ts("expires_at"),
        _ts("ended_at", nullable=True),
        sa.Column("end_reason", sa.String(32), nullable=True),
    )
    op.create_index("ix_agent_sessions_workspace_id", "agent_sessions", ["workspace_id"])
    op.create_index("ix_agent_sessions_installation_ref", "agent_sessions", ["installation_ref"])
    op.create_index("ix_agent_sessions_token_id", "agent_sessions", ["token_id"])
    op.create_index("ix_agent_sessions_env_live", "agent_sessions", ["environment_id", "ended_at"])


def downgrade() -> None:
    op.drop_table("agent_sessions")
    op.drop_table("agent_installations")
