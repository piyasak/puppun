"""SQLAlchemy models for P2.1 (PRD §F).

Every customer-owned row carries `workspace_id`. Passwords, sessions and password reset
live in Supabase Auth (E-27); this database never stores them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
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


class Environment(Base):
    """Agent scope inside a Workspace (architecture §2). Limits and plan caps arrive in P2.3."""

    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = _created()
