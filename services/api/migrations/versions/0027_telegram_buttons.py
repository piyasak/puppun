"""Telegram buttons (Q-52 phase 1.5): people's own Telegram accounts, buttons on sent messages.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ws():
    return sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Expand-only (E-49): one nullable column and two new tables.
    op.add_column("notifications", sa.Column("buttons", postgresql.JSONB()))
    op.create_table(
        "telegram_users",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        _created(),
        sa.Column("unlinked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "telegram_user_id", name="uq_telegram_users_workspace_tg"),
    )
    op.create_index("ix_telegram_users_workspace_id", "telegram_users", ["workspace_id"])
    op.create_index("ix_telegram_users_user_id", "telegram_users", ["user_id"])
    op.create_table(
        "telegram_actions",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("notification_id", UUID, sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_ref", UUID, sa.ForeignKey("telegram_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(24), nullable=False, unique=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("item_id", UUID, sa.ForeignKey("schedule_items.id", ondelete="CASCADE")),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id", ondelete="CASCADE")),
        sa.Column("state_version", sa.Integer()),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_telegram_user_id", sa.BigInteger()),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("result", sa.String(300)),
    )
    op.create_index("ix_telegram_actions_workspace_id", "telegram_actions", ["workspace_id"])
    op.create_index("ix_telegram_actions_notification_id", "telegram_actions", ["notification_id"])


def downgrade() -> None:
    op.drop_table("telegram_actions")
    op.drop_table("telegram_users")
    op.drop_column("notifications", "buttons")
