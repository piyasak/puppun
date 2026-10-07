"""Agent installations and sessions (FR-14, G2-03, architecture §2.1/§2.3).

Rules:
- The Environment always comes from the token row on the server; anything the client sends
  about its Environment is ignored (T05).
- The same installation_id reconnecting reuses its registration (T03); a new one is counted
  against the Environment's registered_agent_limit under a row lock.
- Each installation has at most one live session. A new session bumps the installation's
  generation and ends the previous one (`superseded`); requests from the old one fail (T04).
- Every Agent request re-checks the token, so revoking or expiring it ends the session on the
  next call (well within the 60 s target in PRD §6).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import agent_tokens
from .errors import ApiError
from .models import AgentInstallation, AgentSession, AgentToken, Environment

HEARTBEAT_INTERVAL_S = 15
STALE_AFTER_S = 60
SESSION_TTL_S = 90
SESSION_PREFIX = "cfas_"


def now() -> datetime:
    return datetime.now(UTC)


def hash_session(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def auth_failed() -> ApiError:
    # One answer for unknown token, wrong username, expired or revoked token (T02).
    return ApiError(401, "AGENT_AUTH_FAILED", "ชื่อผู้ใช้หรือ Token ไม่ถูกต้อง หรือ Token ถูกยกเลิก/หมดอายุ")


def live_filter(at: datetime):
    return (AgentSession.ended_at.is_(None), AgentSession.expires_at > at)


def end_sessions(db: Session, *conditions, reason: str) -> int:
    result = db.execute(
        update(AgentSession).where(AgentSession.ended_at.is_(None), *conditions)
        .values(ended_at=now(), end_reason=reason)
    )
    return result.rowcount or 0


@dataclass(frozen=True)
class NewSession:
    session_token: str
    session: AgentSession
    installation: AgentInstallation
    environment: Environment


def authenticate(db: Session, username: str, token: str, installation_id: str, agent_version: str | None) -> NewSession:
    try:
        scope = agent_tokens.verify(db, username, token)
    except agent_tokens.TokenRejected:
        raise auth_failed() from None

    # Serialize registrations and session starts per Environment.
    env = db.scalars(select(Environment).where(Environment.id == scope.environment_id).with_for_update()).one()
    at = now()

    inst = db.scalars(
        select(AgentInstallation).where(
            AgentInstallation.environment_id == env.id, AgentInstallation.installation_id == installation_id)
    ).first()
    if inst is None or inst.deregistered_at is not None:
        registered = db.scalar(
            select(func.count()).select_from(AgentInstallation).where(
                AgentInstallation.environment_id == env.id, AgentInstallation.deregistered_at.is_(None))
        )
        if registered >= env.registered_agent_limit:
            raise ApiError(409, "AGENT_LIMIT_REACHED",
                           "Environment นี้ลงทะเบียน Agent ครบตามจำนวนแล้ว ยกเลิกทะเบียน Agent เก่าในหน้าเว็บก่อน",
                           {"registered": registered, "limit": env.registered_agent_limit})
        if inst is None:
            inst = AgentInstallation(workspace_id=env.workspace_id, environment_id=env.id,
                                     installation_id=installation_id, generation=0)
            db.add(inst)
        else:
            inst.deregistered_at = None  # re-registering after a deregistration counts again (checked above)
        db.flush()

    # Fencing: the previous session of this installation ends before the new one exists.
    # If a check below fails, the request rolls back and the previous session stays as it was.
    end_sessions(db, AgentSession.installation_ref == inst.id, reason="superseded")

    live = db.scalar(
        select(func.count()).select_from(AgentSession).where(
            AgentSession.environment_id == env.id, *live_filter(at), AgentSession.installation_ref != inst.id)
    )
    if live >= env.concurrent_session_limit:
        raise ApiError(409, "SESSION_LIMIT_REACHED",
                       "Session พร้อมกันของ Environment นี้เต็มแล้ว ปิด Agent เครื่องอื่นหรือยกเลิกทะเบียนในหน้าเว็บ",
                       {"live_sessions": live, "limit": env.concurrent_session_limit})

    inst.generation += 1
    inst.agent_version = (agent_version or "")[:32] or None
    inst.last_token_id = scope.token_id
    inst.last_seen_at = at
    db.flush()

    raw = SESSION_PREFIX + secrets.token_urlsafe(32)
    session = AgentSession(
        workspace_id=env.workspace_id, environment_id=env.id, installation_ref=inst.id, token_id=scope.token_id,
        session_hash=hash_session(raw), generation=inst.generation, last_heartbeat_at=at,
        expires_at=at + timedelta(seconds=SESSION_TTL_S),
    )
    db.add(session)
    db.execute(update(AgentToken).where(AgentToken.id == scope.token_id).values(last_used_at=at))
    db.flush()
    return NewSession(raw, session, inst, env)


@dataclass(frozen=True)
class AgentContext:
    session_id: uuid.UUID
    workspace_id: uuid.UUID
    environment_id: uuid.UUID
    installation_ref: uuid.UUID
    generation: int


def session_ended(reason: str) -> ApiError:
    messages = {
        "superseded": "มี Agent อีกตัวเชื่อมต่อด้วยการติดตั้งเดียวกัน Session นี้ถูกแทนที่แล้ว",
        "token_revoked": "Token ถูกยกเลิกหรือหมดอายุ กรุณาใส่ Token ใหม่",
        "deregistered": "Agent นี้ถูกยกเลิกทะเบียนจากหน้าเว็บ",
    }
    return ApiError(401, "AGENT_SESSION_ENDED", messages.get(reason, "Session หมดอายุ กรุณาเชื่อมต่อใหม่"),
                    {"reason": reason})


def resolve(db: Session, raw: str) -> AgentContext:
    """Session from the bearer value; re-checks token, installation and expiry on every call."""
    if not raw.startswith(SESSION_PREFIX):
        raise session_ended("invalid")
    s = db.scalars(select(AgentSession).where(AgentSession.session_hash == hash_session(raw)).with_for_update()).first()
    if s is None:
        raise session_ended("invalid")
    if s.ended_at is not None:
        raise session_ended(s.end_reason or "ended")
    at = now()
    if s.expires_at <= at:
        s.ended_at, s.end_reason = at, "expired"
        db.commit()
        raise session_ended("expired")
    token = db.get(AgentToken, s.token_id)
    if token is None or agent_tokens.status(token, at) != "active":
        s.ended_at, s.end_reason = at, "token_revoked"
        db.commit()
        raise session_ended("token_revoked")
    inst = db.get(AgentInstallation, s.installation_ref)
    if inst.deregistered_at is not None:
        s.ended_at, s.end_reason = at, "deregistered"
        db.commit()
        raise session_ended("deregistered")
    if inst.generation != s.generation:  # belt and braces: a newer session exists
        s.ended_at, s.end_reason = at, "superseded"
        db.commit()
        raise session_ended("superseded")
    return AgentContext(s.id, s.workspace_id, s.environment_id, s.installation_ref, s.generation)


def heartbeat(db: Session, ctx: AgentContext, generation: int) -> AgentSession:
    if generation != ctx.generation:
        raise ApiError(409, "STALE_GENERATION", "Session นี้ไม่ใช่ Session ล่าสุดของ Agent", {"current": ctx.generation})
    at = now()
    s = db.get(AgentSession, ctx.session_id)
    s.last_heartbeat_at = at
    s.expires_at = at + timedelta(seconds=SESSION_TTL_S)
    db.execute(update(AgentInstallation).where(AgentInstallation.id == ctx.installation_ref).values(last_seen_at=at))
    return s


def presence(last_heartbeat: datetime | None, live: bool, at: datetime) -> str:
    """online / stale / offline for the web UI (heartbeat 15 s, stale 60 s, expiry 90 s)."""
    if not live or last_heartbeat is None:
        return "offline"
    return "stale" if (at - last_heartbeat).total_seconds() > STALE_AFTER_S else "online"
