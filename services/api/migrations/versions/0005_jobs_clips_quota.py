"""P3.1: jobs, job events, clips, quota ledger; plan clip quota.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _fk(name, table, ondelete="CASCADE", nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable)


def _ts(name, nullable=False, default=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    # Demo plan quota (D05 open): 30 clips per month.
    op.add_column("plans", sa.Column("clips_per_month", sa.Integer(), nullable=False, server_default="30"))
    op.alter_column("plans", "clips_per_month", server_default=None)

    op.create_table(
        "jobs",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("environment_id", "environments"),
        _fk("created_by", "users", ondelete="SET NULL", nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_label", sa.String(200), nullable=True),
        sa.Column("rights_acceptance_id", sa.Uuid(), sa.ForeignKey("rights_acceptances.id"), nullable=False),
        sa.Column("requested_clips", sa.Integer(), nullable=False),
        sa.Column("planned_clips", sa.Integer(), nullable=True),
        sa.Column("clip_min_s", sa.Integer(), nullable=False),
        sa.Column("clip_max_s", sa.Integer(), nullable=False),
        sa.Column("subtitles", sa.Boolean(), nullable=False),
        sa.Column("review_mode", sa.String(8), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("notice", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("error_detail", sa.String(500), nullable=True),
        sa.Column("source_duration_s", sa.Integer(), nullable=True),
        sa.Column("quota_period", sa.String(7), nullable=True),
        _fk("lease_session_id", "agent_sessions", ondelete="SET NULL", nullable=True),
        _ts("lease_expires_at", nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _ts("created_at", default=True),
        _ts("updated_at", default=True),
        _ts("finished_at", nullable=True),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint("requested_clips BETWEEN 1 AND 20", name="ck_jobs_requested_clips"),
        sa.CheckConstraint("clip_min_s >= 15 AND clip_max_s <= 600 AND clip_min_s <= clip_max_s",
                           name="ck_jobs_clip_bounds"),
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])
    op.create_index("ix_jobs_claimable", "jobs", ["environment_id", "state", "created_at"])

    op.create_table(
        "job_events",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("job_id", "jobs"),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        _ts("created_at", default=True),
        sa.UniqueConstraint("job_id", "event_id"),
    )
    op.create_index("ix_job_events_workspace_id", "job_events", ["workspace_id"])
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.create_table(
        "clips",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("job_id", "jobs"),
        sa.Column("clip_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(40), nullable=False),
        sa.Column("render_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        _ts("created_at", default=True),
        sa.UniqueConstraint("job_id", "clip_index"),
    )
    op.create_index("ix_clips_workspace_id", "clips", ["workspace_id"])
    op.create_index("ix_clips_job_id", "clips", ["job_id"])

    op.create_table(
        "quota_ledger",
        _id(),
        _fk("workspace_id", "workspaces"),
        _fk("job_id", "jobs", ondelete="SET NULL", nullable=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("entry", sa.String(8), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("reason", sa.String(40), nullable=True),
        _ts("created_at", default=True),
        sa.CheckConstraint("units > 0", name="ck_quota_ledger_units_positive"),
    )
    op.create_index("ix_quota_ledger_job_id", "quota_ledger", ["job_id"])
    op.create_index("ix_quota_ledger_ws_period", "quota_ledger", ["workspace_id", "period"])


def downgrade() -> None:
    for table in ("quota_ledger", "clips", "job_events", "jobs"):
        op.drop_table(table)
    op.drop_column("plans", "clips_per_month")
