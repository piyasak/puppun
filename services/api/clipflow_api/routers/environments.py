"""Environments, tenant-scoped (architecture §2). P2.1 covers ownership only; limits come in P2.3."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import Environment
from ..tenancy import get_owned, scoped

router = APIRouter(prefix="/v1/environments")


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _out(env: Environment) -> dict:
    return {"id": str(env.id), "name": env.name, "created_at": env.created_at.isoformat()}


def _name_taken() -> ApiError:
    return ApiError(409, "NAME_TAKEN", "มี Environment ชื่อนี้แล้ว")


@router.get("")
def list_environments(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rows = db.scalars(scoped(Environment, auth.workspace_id).order_by(Environment.created_at)).all()
    return {"items": [_out(e) for e in rows]}


@router.post("", status_code=201)
def create_environment(body: EnvironmentIn, request: Request, auth: WebAuth = Depends(web_auth),
                       db: Session = Depends(get_db)):
    env = Environment(workspace_id=auth.workspace_id, name=body.name.strip())
    db.add(env)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None
    audit.record(db, request, "environment.create", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=env.id)
    db.commit()
    return _out(env)


@router.get("/{environment_id}")
def get_environment(environment_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return _out(get_owned(db, Environment, environment_id, auth.workspace_id))


@router.patch("/{environment_id}")
def rename_environment(environment_id: uuid.UUID, body: EnvironmentIn, request: Request,
                       auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    env = get_owned(db, Environment, environment_id, auth.workspace_id, for_update=True)
    env.name = body.name.strip()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None
    audit.record(db, request, "environment.rename", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=env.id)
    db.commit()
    return _out(env)
