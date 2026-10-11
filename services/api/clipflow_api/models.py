"""SQLAlchemy models for P2.1 (PRD §F).

Every customer-owned row carries `workspace_id`. Passwords, sessions and password reset
live in Supabase Auth (E-27); this database never stores them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _uuid()
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")  # Q-04: only option in MVP
    created_at: Mapped[datetime] = _created()


class User(Base):
    """Application profile of a Supabase Auth user; `id` is the Supabase user id (JWT `sub`)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Copy of the verified token email, refreshed on each request. Supabase owns uniqueness, so no
    # unique constraint here: a stale copy must never block a different account.
    email: Mapped[str] = mapped_column(String(254))
    username: Mapped[str] = mapped_column(String(32), unique=True)  # stored lower-cased; pairs with Agent tokens
    # Platform staff (Q-11, E-46): admin | support | None. Set only by `python -m clipflow_api.manage`.
    platform_role: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    """User ↔ Workspace with a role. MVP: one Owner per Workspace (architecture §2)."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="owner")
    created_at: Mapped[datetime] = _created()


class RightsAcceptance(Base):
    """Q-14: the customer accepts the content-rights declaration once, at sign-up.

    Every job later references the acceptance in force (FR-02) instead of asking per job.
    """

    __tablename__ = "rights_acceptances"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    declaration_version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = _created()


class AuditEvent(Base):
    """Security-relevant actions. Never holds secrets, passwords or tokens."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(500))  # required for staff changes (FR-22)
    details: Mapped[dict | None] = mapped_column(JSONB)  # before/after values, never secrets
    created_at: Mapped[datetime] = _created()


class Plan(Base):
    """Versioned package entitlements (FR-13). Real prices and quotas are open (D05); `is_demo` plans
    exist only so P2 limits can be enforced and tested, and are never offered commercially."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("code", "version"),)

    id: Mapped[uuid.UUID] = _uuid()
    code: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    max_registered_agents: Mapped[int] = mapped_column(Integer)
    max_concurrent_sessions: Mapped[int] = mapped_column(Integer)
    max_devices: Mapped[int] = mapped_column(Integer)
    # quota unit = one rendered clip (FR-21), per cycle; None = unlimited (Business, PO 2026-10-10)
    clips_per_month: Mapped[int | None] = mapped_column(Integer)
    # P6 (E-45): prices are examples until D05; amounts are integer satang, always computed on the server.
    price_satang: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="THB")
    interval_days: Mapped[int] = mapped_column(Integer, default=30)
    is_purchasable: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = _created()


class Subscription(Base):
    """The plan a Workspace is on. One row per Workspace; it is also the lock that serializes
    changes to plan-wide allocations (PRD §F: caps are enforced in transactions)."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(16))  # trial | active | expired (billing.effective decides)
    # The current cycle; quota resets per cycle (ledger period = cycle start date, E-45).
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_cycles_ahead: Mapped[int] = mapped_column(Integer, default=0)  # renewals already paid for
    next_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))  # plan change at next cycle
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Environment(Base):
    """Agent scope inside a Workspace (architecture §2).

    The limits are allocations out of the plan's caps: the sum over all Environments of a
    Workspace never exceeds the plan, so more Environments never mean more entitlement.
    """

    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        CheckConstraint("registered_agent_limit >= 0 AND concurrent_session_limit >= 0 AND device_limit >= 0",
                        name="ck_environments_limits_non_negative"),
        CheckConstraint("concurrent_session_limit <= registered_agent_limit",
                        name="ck_environments_sessions_within_agents"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    registered_agent_limit: Mapped[int] = mapped_column(Integer)
    concurrent_session_limit: Mapped[int] = mapped_column(Integer)
    device_limit: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class AgentPairingCode(Base):
    """A short, single-use code that links an Agent to an Environment (PO 2026-10-10): the web shows
    it, the Agent sends it once and receives its own Agent token. Only a SHA-256 of the code is kept;
    it lasts 10 minutes."""

    __tablename__ = "agent_pairing_codes"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_tokens.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class AgentToken(Base):
    """Agent credential (FR-12). Only a public prefix and a SHA-256 of the full token are stored;
    the token itself is shown once at creation. Scope = workspace + environment, server-side."""

    __tablename__ = "agent_tokens"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_tokens.id", ondelete="SET NULL"))

class AgentInstallation(Base):
    """One Agent install, registered against an Environment (FR-14).

    `installation_id` is generated once by the Agent and kept on disk. It identifies an
    install; it is not proof of a real machine (PRD §6). Reconnecting with the same id
    reuses this row, so it does not consume another registration (T03).
    """

    __tablename__ = "agent_installations"
    __table_args__ = (UniqueConstraint("environment_id", "installation_id"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), index=True)
    installation_id: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    last_token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_tokens.id", ondelete="SET NULL"))
    generation: Mapped[int] = mapped_column(Integer)  # bumps on every new session (fencing)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deregistered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentLibrary(Base):
    """The videos folder of an Environment's Agent (PO 2026-10-11), as last reported: full videos at
    the top (cut by the Agent) and sub-folders of clips already cut, in EP order. Names and sizes only."""

    __tablename__ = "agent_libraries"

    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"),
                                                      primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    installation_ref: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_installations.id", ondelete="SET NULL"))
    videos: Mapped[list] = mapped_column(JSONB)  # [{name, size_bytes, modified_at}]
    sets: Mapped[list] = mapped_column(JSONB)  # [{folder, clips: [name], count, size_bytes}]
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentSession(Base):
    """Short-lived Agent session (architecture §2.3). At most one live session per installation:
    a new one ends the previous (`superseded`), and requests carrying an old generation fail."""

    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_env_live", "environment_id", "ended_at"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    installation_ref: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_installations.id", ondelete="CASCADE"),
                                                        index=True)
    token_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_tokens.id", ondelete="CASCADE"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    generation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(32))


class Device(Base):
    """An Android phone bound to an Environment (FR-15, architecture §2.4).

    The serial identifies the phone; it is never proof of ownership. At most one active
    binding per serial across all Workspaces (partial unique index on `serial_key`), and a
    conflicting binding is refused, never moved silently.
    """

    __tablename__ = "devices"
    __table_args__ = (
        Index("uq_devices_active_serial", "serial_key", unique=True,
              postgresql_where=text("unbound_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), index=True)
    serial: Mapped[str] = mapped_column(String(64))  # as reported (case preserved)
    serial_key: Mapped[str] = mapped_column(String(64))  # normalized for comparison
    model: Mapped[str | None] = mapped_column(String(64))
    android_version: Mapped[str | None] = mapped_column(String(16))
    display_name: Mapped[str | None] = mapped_column(String(60))
    expected_account: Mapped[str | None] = mapped_column(String(64))  # TikTok handle the phone must post as
    registered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_installations.id", ondelete="SET NULL"))
    last_state: Mapped[str | None] = mapped_column(String(16))  # device | unauthorized | offline | missing
    thai_keyboard: Mapped[bool | None] = mapped_column(Boolean)  # ADBKeyboard installed (Q-44); None = not reported
    last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """A request to make clips from one source (FR-02..FR-05). Rendering happens on the
    customer's Agent (Q-15); the server owns state, quota and approval.

    States: RECEIVED -> SOURCE_VALIDATED -> DOWNLOADING -> ANALYZING -> RENDERING ->
    READY_FOR_REVIEW, or FAILED / NEEDS_ACTION / CANCELLED. Agent work is leased: only the
    session holding the current lease (and its generation) may report events.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key"),
        Index("ix_jobs_claimable", "environment_id", "state", "created_at"),
        CheckConstraint("requested_clips BETWEEN 1 AND 100", name="ck_jobs_requested_clips"),
        CheckConstraint("clip_min_s >= 15 AND clip_max_s <= 600 AND clip_min_s <= clip_max_s",
                        name="ck_jobs_clip_bounds"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(16))  # youtube | bilibili | local_file
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_label: Mapped[str | None] = mapped_column(String(200))  # file name for local_file; no full path
    rights_acceptance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rights_acceptances.id"))
    requested_clips: Mapped[int] = mapped_column(Integer)
    # Q-32: split the whole source; the count follows the source (requested_clips is then the cap).
    auto_clips: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # PO 2026-10-10: delete each clip's file on the Agent's PC once it is posted (verified), to keep space
    delete_after_post: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    planned_clips: Mapped[int | None] = mapped_column(Integer)
    clip_min_s: Mapped[int] = mapped_column(Integer)
    clip_max_s: Mapped[int] = mapped_column(Integer)
    subtitles: Mapped[bool] = mapped_column(Boolean)
    review_mode: Mapped[str] = mapped_column(String(8))  # review | auto
    # PO 2026-10-11: set when the job is made, so clips start with the final text (and auto mode needs no edit)
    caption_title: Mapped[str | None] = mapped_column(String(100))  # caption = "<title> — ตอนที่ i/N"
    caption_hashtags: Mapped[list | None] = mapped_column(JSONB)  # replaces the generated hashtags
    seed: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    state_version: Mapped[int] = mapped_column(Integer)
    notice: Mapped[str | None] = mapped_column(String(32))  # e.g. INSUFFICIENT_SOURCE
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(String(500))
    source_duration_s: Mapped[int | None] = mapped_column(Integer)
    quota_period: Mapped[str | None] = mapped_column(String(40))  # cycle key of the reservation (billing.cycle_key)
    lease_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Start again (PO 2026-10-10): set while the Agent remakes missing clip files of a delivered job
    remake_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class JobEvent(Base):
    """Agent events, deduplicated by the Agent's event id (redelivery is harmless)."""

    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "event_id"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()


class Clip(Base):
    """One rendered clip as reported by the Agent (PRD §F: interval, seed, template, hash).

    The file itself is uploaded and checked against `render_sha256` in P3.2.
    """

    __tablename__ = "clips"
    __table_args__ = (UniqueConstraint("job_id", "clip_index"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    clip_index: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    template_version: Mapped[str] = mapped_column(String(40))
    render_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(200))  # burned into the video: changing it means a re-render
    created_at: Mapped[datetime] = _created()
    # P3.2: the uploaded file, server-side checks, metadata version and approval.
    storage_key: Mapped[str | None] = mapped_column(String(300))  # the clip file, when it was uploaded (before Q-33)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # delivered (file or Agent report)
    # Q-33: "agent" = the file stays on the Agent's PC (agent_path); the server keeps a still (preview_key).
    file_location: Mapped[str] = mapped_column(String(8), default="server", server_default="server")
    preview_key: Mapped[str | None] = mapped_column(String(300))
    agent_path: Mapped[str | None] = mapped_column(String(500))
    check_status: Mapped[str | None] = mapped_column(String(8))  # passed | failed | skipped
    check_results: Mapped[dict | None] = mapped_column(JSONB)
    metadata_version: Mapped[int] = mapped_column(Integer, default=1)
    approved_metadata_version: Mapped[int | None] = mapped_column(Integer)
    approved_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approval_mode: Mapped[str | None] = mapped_column(String(8))  # manual | auto
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # retention (NF-06)
    # The installation that rendered the clip and keeps its file (Q-33), and when it deleted it after posting
    agent_installation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_installations.id", ondelete="SET NULL"))
    agent_file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClipMetadata(Base):
    """Posting text for a clip, one row per version (FR-07, PRD §F). Editing creates a new
    version; an approval names the version it approved, so an edit voids it automatically."""

    __tablename__ = "clip_metadata"
    __table_args__ = (UniqueConstraint("clip_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(String(2200))  # TikTok caption limit
    hashtags: Mapped[list] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class QuotaLedger(Base):
    """Append-only quota trail in integer clip units (FR-21, PRD §F).

    reserve: units held for a job; settle: a held unit became a delivered clip; release: a
    held unit returned. Every entry has a unique idempotency key, so a repeated event can
    never charge or refund twice (T10). Used = reserve - release; available = quota - used.
    """

    __tablename__ = "quota_ledger"
    __table_args__ = (
        CheckConstraint("units > 0", name="ck_quota_ledger_units_positive"),
        Index("ix_quota_ledger_ws_period", "workspace_id", "period"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    period: Mapped[str] = mapped_column(String(40))  # subscription cycle start (UTC, billing.cycle_key)
    entry: Mapped[str] = mapped_column(String(8))  # reserve | settle | release
    units: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _created()


class ScheduleSeries(Base):
    """One posting plan: the approved clips of a job, one phone, every X hours inside a daily
    window (FR-09..FR-11, PRD §5/§G). States: ACTIVE, PAUSED, CANCELLED, COMPLETED."""

    __tablename__ = "schedule_series"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key"),
        CheckConstraint("interval_hours BETWEEN 1 AND 168", name="ck_series_interval"),
        CheckConstraint("window_start_min >= 0 AND window_end_min <= 1440 AND window_start_min < window_end_min",
                        name="ck_series_window"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64))
    window_start_min: Mapped[int] = mapped_column(Integer)
    window_end_min: Mapped[int] = mapped_column(Integer)
    interval_hours: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    offline_policy: Mapped[str] = mapped_column(String(8))  # defer | skip (Q-06)
    state: Mapped[str] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ScheduleItem(Base):
    """One clip at one time on one phone. It names the exact approved version it may post
    (metadata version + file hash), never "the latest" (PRD §F). Scheduled, claimed, started,
    submitted and verified times are kept apart (PRD §G.8).

    States so far: SCHEDULED, NEEDS_ACTION (approval no longer matches), CANCELLED, SKIPPED;
    the publish states (CLAIMED ... VERIFIED_SUCCESS / UNKNOWN) arrive with dispatch.
    """

    __tablename__ = "schedule_items"
    __table_args__ = (
        UniqueConstraint("series_id", "seq"),
        # A clip is in at most one live item: never posted twice by two series (G4-02).
        Index("uq_schedule_items_live_clip", "clip_id", unique=True,
              postgresql_where=text("state NOT IN ('CANCELLED', 'SKIPPED')")),
        Index("ix_schedule_items_device_time", "device_id", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_series.id", ondelete="CASCADE"), index=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_version: Mapped[int] = mapped_column(Integer)
    clip_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    state_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(40))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # P4.3: the Agent session holding the post, its lease, delivery count and result evidence.
    lease_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_sessions.id", ondelete="SET NULL"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    # Q-42: the mode this post was handed out with (dry_run | live; NULL before 0018) and the grant
    # that allows it. grant_used is set once, under the grant's row lock, at SUBMITTING.
    posting_mode: Mapped[str | None] = mapped_column(String(8))
    grant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posting_grants.id", ondelete="SET NULL"))
    grant_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class PostingGrant(Base):
    """Permission for real posts (Q-42): one Workspace, one TikTok account, up to `max_posts` posts
    until `expires_at`, given by a platform admin with a reason. Without a valid grant every post is
    a dry run. `used_posts` only grows, under this row's lock, when a post reaches SUBMITTING."""

    __tablename__ = "posting_grants"
    __table_args__ = (
        CheckConstraint("max_posts BETWEEN 1 AND 1000", name="ck_posting_grants_max"),
        CheckConstraint("used_posts >= 0 AND used_posts <= max_posts", name="ck_posting_grants_used"),
        CheckConstraint("visibility IN ('only_me')", name="ck_posting_grants_visibility"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    account: Mapped[str] = mapped_column(String(64))  # TikTok handle, lower case, no "@"
    visibility: Mapped[str] = mapped_column(String(16))  # only_me (public needs a PO decision + a tested step)
    max_posts: Mapped[int] = mapped_column(Integer)
    used_posts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ScheduleItemEvent(Base):
    """Agent events for a post, deduplicated by the Agent's event id."""

    __tablename__ = "schedule_item_events"
    __table_args__ = (UniqueConstraint("item_id", "event_id"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_items.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created()


class Payment(Base):
    """One checkout (FR-20). Amount, currency and plan version come from the server; status changes
    only through verified provider events, never from the browser's redirect (PRD §8, E-45)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_ref"),
        UniqueConstraint("workspace_id", "idempotency_key"),
        CheckConstraint("amount_satang > 0", name="ck_payments_amount_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    amount_satang: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(24))
    provider_ref: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(12))  # pending | succeeded | failed | refunded
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    applied: Mapped[str | None] = mapped_column(String(16))  # started | queued | removed: what it did to the subscription
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentEvent(Base):
    """Verified provider events, unique per (provider, event_id): a repeat changes nothing (PRD §F)."""

    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[uuid.UUID] = _uuid()
    provider: Mapped[str] = mapped_column(String(24))
    event_id: Mapped[str] = mapped_column(String(80))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(24))  # applied | ignored_out_of_order | ...
    payload_sha256: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = _created()
