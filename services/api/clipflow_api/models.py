"""SQLAlchemy models for P2.1 (PRD §F).

Every customer-owned row carries `workspace_id`. Passwords, sessions and password reset
live in Supabase Auth (E-27); this database never stores them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
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
    created_at: Mapped[datetime] = _created()


class Subscription(Base):
    """The plan a Workspace is on. One row per Workspace; it is also the lock that serializes
    changes to plan-wide allocations (PRD §F: caps are enforced in transactions)."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(16))  # active | past_due | cancelled (billing arrives in P6)
    created_at: Mapped[datetime] = _created()


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
