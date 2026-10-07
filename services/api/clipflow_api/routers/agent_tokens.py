"""Agent token lifecycle for the web app: generate (shown once), list, revoke, rotate (FR-12, G2-02).

Revoking or rotating also ends the token's Agent sessions once sessions exist (P2.5): the
session check reads `revoked_at` on every Agent request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import agent_tokens, audit
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import AgentToken, Environment
from ..tenancy import get_owned, scoped

router = APIRouter(prefix="/v1/agent-tokens")

MAX_ACTIVE_PER_ENVIRONMENT = 10


class TokenIn(BaseModel):
    environment_id: uuid.UUID
    name: str = Field(min_length=1, max_length=60)
    expires_in_days: int = Field(default=90, ge=1, le=365)


def _out(row: AgentToken, env_name: str) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "prefix": row.prefix,  # public part, lets the user match a token to an installation
        "environment": {"id": str(row.environment_id), "name": env_name},
        "status": agent_tokens.status(row),
        "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "rotated_from_id": str(row.rotated_from_id) if row.rotated_from_id else None,
    }


def _issue(db: Session, auth: WebAuth, env: Environment, name: str, days: int,
           rotated_from: uuid.UUID | None = None) -> tuple[AgentToken, str]:
    token, prefix, digest = agent_tokens.generate()
    row = AgentToken(
        workspace_id=auth.workspace_id, environment_id=env.id, name=name, prefix=prefix, secret_hash=digest,
        created_by=auth.user_id, expires_at=datetime.now(UTC) + timedelta(days=days), rotated_from_id=rotated_from,
    )
    db.add(row)
    db.flush()
    return row, token


def _secret_response(response: Response) -> None:
    # The body carries a credential: never cache it anywhere.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("", status_code=201)
def create_token(body: TokenIn, request: Request, response: Response, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    env = get_owned(db, Environment, body.environment_id, auth.workspace_id, for_update=True)
    active = db.scalar(
        select(func.count()).select_from(AgentToken).where(
            AgentToken.environment_id == env.id, AgentToken.revoked_at.is_(None),
            AgentToken.expires_at > datetime.now(UTC))
    )
    if active >= MAX_ACTIVE_PER_ENVIRONMENT:
        raise ApiError(409, "TOKEN_LIMIT", f"Environment นี้มี Token ที่ใช้งานได้ครบ {MAX_ACTIVE_PER_ENVIRONMENT} อันแล้ว")
    row, token = _issue(db, auth, env, body.name.strip(), body.expires_in_days)
    audit.record(db, request, "agent_token.create", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=row.id)
    db.commit()
    _secret_response(response)
    return {**_out(row, env.name), "token": token}


@router.get("")
def list_tokens(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rows = db.execute(
        scoped(AgentToken, auth.workspace_id)
        .join(Environment, Environment.id == AgentToken.environment_id)
        .add_columns(Environment.name)
        .order_by(AgentToken.created_at.desc())
    ).all()
    return {"items": [_out(row, env_name) for row, env_name in rows]}


@router.post("/{token_id}/revoke")
def revoke_token(token_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    """Idempotent: revoking an already revoked token keeps the first revocation time."""
    row = get_owned(db, AgentToken, token_id, auth.workspace_id, for_update=True)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        audit.record(db, request, "agent_token.revoke", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=row.id)
    db.commit()
    return _out(row, db.get(Environment, row.environment_id).name)


@router.post("/{token_id}/rotate", status_code=201)
def rotate_token(token_id: uuid.UUID, request: Request, response: Response, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    """New token for the same Environment and name; the old one is revoked in the same transaction."""
    old = get_owned(db, AgentToken, token_id, auth.workspace_id, for_update=True)
    if old.revoked_at is not None:
        raise ApiError(409, "TOKEN_REVOKED", "Token นี้ถูกยกเลิกแล้ว สร้าง Token ใหม่แทน")
    env = db.get(Environment, old.environment_id)
    old.revoked_at = datetime.now(UTC)
    days = max(1, round((old.expires_at - old.created_at).total_seconds() / 86400))
    row, token = _issue(db, auth, env, old.name, min(days, 365), rotated_from=old.id)
    audit.record(db, request, "agent_token.rotate", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=row.id)
    db.commit()
    _secret_response(response)
    return {**_out(row, env.name), "token": token}
