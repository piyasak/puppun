"""Environments with limits allocated out of the plan (FR-13, G2-03). Tenant-scoped."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, quota
from ..agent_sessions import now
from ..deps import WebAuth, get_db, web_auth
from ..entitlements import LIMITS, allocated, check_allocation, entitlement, in_use
from ..errors import ApiError
from ..models import Environment
from ..tenancy import get_owned, scoped

router = APIRouter(prefix="/v1")

def _sessions_within_agents(agents: int | None, sessions: int | None) -> None:
    if agents is not None and sessions is not None and sessions > agents:
        raise ValueError("concurrent_session_limit_above_registered_agent_limit")


class EnvironmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    registered_agent_limit: int = Field(default=1, ge=0, le=1000)
    concurrent_session_limit: int = Field(default=1, ge=0, le=1000)
    device_limit: int = Field(default=1, ge=0, le=1000)

    @model_validator(mode="after")
    def _check(self):
        _sessions_within_agents(self.registered_agent_limit, self.concurrent_session_limit)
        return self


class EnvironmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    registered_agent_limit: int | None = Field(default=None, ge=0, le=1000)
    concurrent_session_limit: int | None = Field(default=None, ge=0, le=1000)
    device_limit: int | None = Field(default=None, ge=0, le=1000)


def _out(env: Environment) -> dict:
    return {
        "id": str(env.id),
        "name": env.name,
        "registered_agent_limit": env.registered_agent_limit,
        "concurrent_session_limit": env.concurrent_session_limit,
        "device_limit": env.device_limit,
        "created_at": env.created_at.isoformat(),
    }


def _name_taken() -> ApiError:
    return ApiError(409, "NAME_TAKEN", "มี Environment ชื่อนี้แล้ว")


@router.get("/workspace/usage")
def workspace_usage(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """Authoritative plan caps and how much of them the Environments have allocated.

    `in_use` counts registered Agents, live sessions and bound devices.
    """
    ent = entitlement(db, auth.workspace_id)
    return {
        "plan": {"code": ent.plan.code, "version": ent.plan.version, "name": ent.plan.name,
                 "is_demo": ent.plan.is_demo, "status": ent.cycle.status},
        "caps": {name: ent.cap(name) for name in LIMITS},
        "allocated": allocated(db, auth.workspace_id),
        "in_use": in_use(db, workspace_id=auth.workspace_id),
        "clips": quota.summary(db, auth.workspace_id, now()),
    }


@router.get("/environments")
def list_environments(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rows = db.scalars(scoped(Environment, auth.workspace_id).order_by(Environment.created_at)).all()
    return {"items": [_out(e) for e in rows]}


@router.post("/environments", status_code=201)
def create_environment(body: EnvironmentIn, request: Request, auth: WebAuth = Depends(web_auth),
                       db: Session = Depends(get_db)):
    entitlement(db, auth.workspace_id, lock=True)
    requested = {name: getattr(body, name) for name in LIMITS}
    check_allocation(db, auth.workspace_id, requested)
    env = Environment(workspace_id=auth.workspace_id, name=body.name.strip(), **requested)
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


@router.get("/environments/{environment_id}")
def get_environment(environment_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return _out(get_owned(db, Environment, environment_id, auth.workspace_id))


@router.patch("/environments/{environment_id}")
def update_environment(environment_id: uuid.UUID, body: EnvironmentPatch, request: Request,
                       auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    entitlement(db, auth.workspace_id, lock=True)
    env = get_owned(db, Environment, environment_id, auth.workspace_id, for_update=True)
    new = {name: (getattr(body, name) if getattr(body, name) is not None else getattr(env, name)) for name in LIMITS}
    try:
        _sessions_within_agents(new["registered_agent_limit"], new["concurrent_session_limit"])
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "จำนวน Session พร้อมกันต้องไม่เกินจำนวน Agent ที่ลงทะเบียนได้",
                       {"fields": [{"field": "concurrent_session_limit", "reason": "above_registered_agent_limit"}]}) from None
    check_allocation(db, auth.workspace_id, new, exclude=env.id)
    used = in_use(db, environment_id=env.id)
    below = [{"limit": k, "in_use": used[k], "requested": new[k]} for k in used if new[k] < used[k]]
    if below:
        raise ApiError(409, "LIMIT_BELOW_USAGE", "ตั้งค่าต่ำกว่าที่ใช้อยู่ไม่ได้ ยกเลิกทะเบียน Agent ที่ไม่ใช้ก่อน",
                       {"limits": below})
    for name, value in new.items():
        setattr(env, name, value)
    if body.name is not None:
        env.name = body.name.strip()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None
    audit.record(db, request, "environment.update", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=env.id)
    db.commit()
    return _out(env)
