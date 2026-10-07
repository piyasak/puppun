"""P2.1 baseline: workspaces, users (Supabase Auth profiles), memberships, rights, audit, environments.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _ts(name: str, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def _fk(name: str, table: str, ondelete: str = "CASCADE", nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "workspaces",
        _id(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        _ts("created_at", default=True),
    )
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        _ts("created_at", default=True),
    )
    op.create_table(
        "memberships",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("user_id", "users"),
        sa.Column("role", sa.String(16), nullable=False),
        _ts("created_at", default=True),
        sa.UniqueConstraint("workspace_id", "user_id"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "rights_acceptances",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("user_id", "users"),
        sa.Column("declaration_version", sa.String(32), nullable=False),
        _ts("accepted_at", default=True),
    )
    op.create_index("ix_rights_acceptances_workspace_id", "rights_acceptances", ["workspace_id"])

    op.create_table(
        "audit_events",
        _id(),
        _fk("workspace_id", "workspaces", ondelete="SET NULL", nullable=True),
        _fk("actor_user_id", "users", ondelete="SET NULL", nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        _ts("created_at", default=True),
    )
    op.create_index("ix_audit_events_workspace_created", "audit_events", ["workspace_id", "created_at"])

    op.create_table(
        "environments",
        _id(),
        _fk("workspace_id", "workspaces"),
        sa.Column("name", sa.String(60), nullable=False),
        _ts("created_at", default=True),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    op.create_index("ix_environments_workspace_id", "environments", ["workspace_id"])


def downgrade() -> None:
    for table in ("environments", "audit_events", "rights_acceptances", "memberships", "users", "workspaces"):
        op.drop_table(table)
