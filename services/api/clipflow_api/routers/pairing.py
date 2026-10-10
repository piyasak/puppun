"""Pairing codes (PO 2026-10-10): link an Agent to an Environment without copying a token.

The web makes a short code (8 characters, shown as XXXX-XXXX, 10 minutes, single use). The Agent's
setup window sends it once and receives its own Agent token, which it stores encrypted; the person
never sees or copies the token. Only a SHA-256 of the code is stored. A wrong, used or expired code
gets the same answer, and the Agent sign-in rate limit applies.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import AgentPairingCode, AgentToken, Environment, User
from ..tenancy import get_owned
from .agent_tokens import MAX_ACTIVE_PER_ENVIRONMENT, _issue, _secret_response

web_router = APIRouter(prefix="/v1/agent-pairing-codes")
agent_router = APIRouter(prefix="/v1/agent")

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: read off a screen and typed
CODE_LEN = 8
TTL = timedelta(minutes=10)
TOKEN_DAYS = 365  # the token the Agent receives; the person can revoke it on the Agent Token page
OPEN_PER_ENVIRONMENT = 5


def normalize(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "").upper()


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


class CodeIn(BaseModel):
    environment_id: uuid.UUID


@web_router.post("", status_code=201)
def create_code(body: CodeIn, request: Request, response: Response, auth: WebAuth = Depends(web_auth),
                db: Session = Depends(get_db)):
    env = get_owned(db, Environment, body.environment_id, auth.workspace_id, for_update=True)
    at = datetime.now(UTC)
    tokens = db.scalar(select(func.count()).select_from(AgentToken).where(
        AgentToken.environment_id == env.id, AgentToken.revoked_at.is_(None), AgentToken.expires_at > at))
    if tokens >= MAX_ACTIVE_PER_ENVIRONMENT:
        raise ApiError(409, "TOKEN_LIMIT", f"Environment นี้มี Token ที่ใช้งานได้ครบ {MAX_ACTIVE_PER_ENVIRONMENT} อันแล้ว "
                                           "ยกเลิก Token ที่ไม่ใช้ก่อน")
    open_codes = db.scalar(select(func.count()).select_from(AgentPairingCode).where(
        AgentPairingCode.environment_id == env.id, AgentPairingCode.used_at.is_(None),
        AgentPairingCode.expires_at > at))
    if open_codes >= OPEN_PER_ENVIRONMENT:
        raise ApiError(429, "TOO_MANY_CODES", "สร้างรหัสไว้หลายอันแล้ว ใช้รหัสเดิมหรือรอให้หมดอายุ (10 นาที)")
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    row = AgentPairingCode(workspace_id=auth.workspace_id, environment_id=env.id, created_by=auth.user_id,
                           code_hash=code_hash(code), expires_at=at + TTL)
    db.add(row)
    db.flush()
    audit.record(db, request, "agent_pairing_code.create", workspace_id=auth.workspace_id,
                 actor_user_id=auth.user_id, target_id=row.id)
    db.commit()
    _secret_response(response)
    return {"code": f"{code[:4]}-{code[4:]}", "expires_at": row.expires_at.isoformat(),
            "expires_in_s": int(TTL.total_seconds()), "environment": {"id": str(env.id), "name": env.name}}


class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    computer_name: str = Field(default="", max_length=40)


@dataclass
class _Issuer:  # what agent_tokens._issue needs from a web identity: the code's creator
    user_id: uuid.UUID
    workspace_id: uuid.UUID


def _invalid() -> ApiError:
    return ApiError(400, "PAIRING_CODE_INVALID", "รหัสเชื่อมต่อไม่ถูกต้อง ใช้ไปแล้ว หรือหมดอายุ — สร้างรหัสใหม่ในหน้า Agent บนเว็บ")


@agent_router.post("/pair")
def pair(body: PairIn, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "unknown"
    request.app.state.agent_auth_limiter.hit(client)  # same budget as Agent sign-in: no guessing
    row = db.scalars(select(AgentPairingCode).where(AgentPairingCode.code_hash == code_hash(body.code))
                     .with_for_update()).first()
    at = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= at:
        raise _invalid()
    env = db.get(Environment, row.environment_id)
    user = db.get(User, row.created_by)
    name = f"PC {body.computer_name.strip()}".strip()[:60] or "PC"
    token_row, token = _issue(db, _Issuer(row.created_by, row.workspace_id), env, name, TOKEN_DAYS)
    row.used_at, row.token_id = at, token_row.id
    audit.record(db, request, "agent_pairing_code.used", workspace_id=row.workspace_id, target_id=token_row.id)
    db.commit()
    _secret_response(response)
    return {"username": user.username, "token": token, "environment": {"id": str(env.id), "name": env.name},
            "token_expires_at": token_row.expires_at.isoformat()}
