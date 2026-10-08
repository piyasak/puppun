"""P4.1: schedule series and items bound to approved clip versions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_series",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("window_start_min", sa.Integer(), nullable=False),
        sa.Column("window_end_min", sa.Integer(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offline_policy", sa.String(8), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint("interval_hours BETWEEN 1 AND 168", name="ck_series_interval"),
        sa.CheckConstraint("window_start_min >= 0 AND window_end_min <= 1440 AND window_start_min < window_end_min",
                           name="ck_series_window"),
    )
    for col in ("workspace_id", "job_id", "device_id"):
        op.create_index(f"ix_schedule_series_{col}", "schedule_series", [col])

    op.create_table(
        "schedule_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("series_id", sa.Uuid(), sa.ForeignKey("schedule_series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clip_id", sa.Uuid(), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
        sa.Column("clip_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("series_id", "seq"),
    )
    op.create_index("ix_schedule_items_workspace_id", "schedule_items", ["workspace_id"])
    op.create_index("ix_schedule_items_series_id", "schedule_items", ["series_id"])
    op.create_index("ix_schedule_items_device_time", "schedule_items", ["device_id", "scheduled_at"])
    op.create_index("uq_schedule_items_live_clip", "schedule_items", ["clip_id"], unique=True,
                    postgresql_where=sa.text("state NOT IN ('CANCELLED', 'SKIPPED')"))


def downgrade() -> None:
    op.drop_table("schedule_items")
    op.drop_table("schedule_series")
