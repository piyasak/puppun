"""Telegram notifications (Q-52, PO 2026-10-16): linked chats, link codes, per-phone rules, an outbox,
and the account numbers the Agent reads on Profile (followers, likes, newest videos' views).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ws():
    return sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Expand-only (E-49): new tables.
    op.create_table(
        "telegram_chats",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("linked_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created(),
        sa.Column("unlinked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "chat_id", name="uq_telegram_chats_workspace_chat"),
    )
    op.create_index("ix_telegram_chats_workspace_id", "telegram_chats", ["workspace_id"])
    op.create_table(
        "telegram_link_codes",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_telegram_link_codes_workspace_id", "telegram_link_codes", ["workspace_id"])
    op.create_table(
        "notify_rules",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("chat_ref", UUID, sa.ForeignKey("telegram_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id", ondelete="CASCADE")),
        sa.Column("posting", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("problems", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("health", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("summary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("summary_hour", sa.Integer(), nullable=False, server_default="21"),
        _created(),
    )
    op.create_index("ix_notify_rules_workspace_id", "notify_rules", ["workspace_id"])
    op.create_index("ix_notify_rules_chat_ref", "notify_rules", ["chat_ref"])
    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("chat_ref", UUID, sa.ForeignKey("telegram_chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("dedupe_key", sa.String(120), nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("batch", sa.Boolean(), nullable=False, server_default=sa.false()),
        _created(),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(300)),
        sa.UniqueConstraint("chat_ref", "dedupe_key", name="uq_notifications_chat_dedupe"),
    )
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])
    op.create_index("ix_notifications_sent_at", "notifications", ["sent_at"])
    op.create_table(
        "account_stats",
        sa.Column("id", UUID, primary_key=True), _ws(),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account", sa.String(64)),
        sa.Column("followers", sa.BigInteger()),
        sa.Column("following", sa.BigInteger()),
        sa.Column("likes", sa.BigInteger()),
        sa.Column("video_views", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_stats_workspace_id", "account_stats", ["workspace_id"])
    op.create_index("ix_account_stats_device_id", "account_stats", ["device_id"])
    op.create_index("ix_account_stats_captured_at", "account_stats", ["captured_at"])


def downgrade() -> None:
    for table in ("account_stats", "notifications", "notify_rules", "telegram_link_codes", "telegram_chats"):
        op.drop_table(table)
