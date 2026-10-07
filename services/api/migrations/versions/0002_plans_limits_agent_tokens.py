"""P2.3/P2.4: demo plan + subscriptions, Environment limits, Agent tokens.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Demo entitlements only (D05 open). Code + version identify a plan; ids are random.
DEMO_PLAN = {"code": "trial", "version": 1, "name": "ทดลองใช้ (Demo — ยังไม่ใช่แพ็กเกจขายจริง)", "is_demo": True,
             "max_registered_agents": 2, "max_concurrent_sessions": 2, "max_devices": 3}


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("max_registered_agents", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_sessions", sa.Integer(), nullable=False),
        sa.Column("max_devices", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", "version"),
    )
    plan_id = uuid.uuid4()
    op.bulk_insert(plans, [{"id": plan_id, **DEMO_PLAN}])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
                  unique=True),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Existing (development) Workspaces start on the demo plan.
    op.execute(sa.text(
        "insert into subscriptions (id, workspace_id, plan_id, status) "
        "select gen_random_uuid(), id, :plan, 'active' from workspaces"
    ).bindparams(plan=plan_id))

    for col in ("registered_agent_limit", "concurrent_session_limit", "device_limit"):
        op.add_column("environments", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.alter_column("environments", col, server_default=None)
    op.create_check_constraint(
        "ck_environments_limits_non_negative", "environments",
        "registered_agent_limit >= 0 AND concurrent_session_limit >= 0 AND device_limit >= 0")
    op.create_check_constraint(
        "ck_environments_sessions_within_agents", "environments",
        "concurrent_session_limit <= registered_agent_limit")

    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.Uuid(), sa.ForeignKey("agent_tokens.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_agent_tokens_workspace_id", "agent_tokens", ["workspace_id"])
    op.create_index("ix_agent_tokens_environment_id", "agent_tokens", ["environment_id"])


def downgrade() -> None:
    op.drop_table("agent_tokens")
    op.drop_constraint("ck_environments_sessions_within_agents", "environments", type_="check")
    op.drop_constraint("ck_environments_limits_non_negative", "environments", type_="check")
    for col in ("device_limit", "concurrent_session_limit", "registered_agent_limit"):
        op.drop_column("environments", col)
    op.drop_table("subscriptions")
    op.drop_table("plans")
