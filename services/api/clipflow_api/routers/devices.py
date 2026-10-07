"""Registered devices: Agent registration/report and the web list/edit/unbind (FR-15, G2-04)."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import agent_sessions, audit, devices
from ..agent_sessions import AgentContext
from ..deps import WebAuth, get_db, web_auth
from ..models import AgentSession, Device, Environment
from ..tenancy import get_owned, scoped
from .agent import agent_context

agent_router = APIRouter(prefix="/v1/agent/devices")
web_router = APIRouter(prefix="/v1/devices")


class RegisterIn(BaseModel):
    serial: str = Field(min_length=1, max_length=128)
    adb_state: str = Field(max_length=16)
    model: str | None = Field(default=None, max_length=64)
    android_version: str | None = Field(default=None, max_length=16)


class ReportIn(BaseModel):
    devices: dict[str, str] = Field(default_factory=dict, max_length=50)  # serial -> adb state


HANDLE_RE = re.compile(r"^@?[A-Za-z0-9._]{2,24}$")


class DevicePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    expected_account: str | None = Field(default=None, max_length=25)

    @field_validator("expected_account")
    @classmethod
    def _handle(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if not HANDLE_RE.match(v):
            raise ValueError("handle_invalid")
        return v.lstrip("@").lower()


def _out(d: Device, env_name: str, agent_online: bool) -> dict:
    return {
        "id": str(d.id),
        "serial": d.serial,
        "model": d.model,
        "android_version": d.android_version,
        "display_name": d.display_name,
        "expected_account": d.expected_account,
        "environment": {"id": str(d.environment_id), "name": env_name},
        "readiness": devices.readiness(d, agent_online),
        "last_reported_at": d.last_reported_at.isoformat() if d.last_reported_at else None,
        "created_at": d.created_at.isoformat(),
        "unbound_at": d.unbound_at.isoformat() if d.unbound_at else None,
    }


@agent_router.post("/register")
def register(body: RegisterIn, request: Request, ctx: AgentContext = Depends(agent_context),
             db: Session = Depends(get_db)):
    device, created = devices.register(db, ctx, body.serial, body.adb_state, body.model, body.android_version)
    if created:
        audit.record(db, request, "device.register", workspace_id=ctx.workspace_id, target_id=device.id)
    db.commit()
    return {"id": str(device.id), "serial": device.serial, "created": created,
            "environment_id": str(device.environment_id)}


@agent_router.post("/report")
def report(body: ReportIn, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    updated = devices.report(db, ctx, body.devices)
    db.commit()
    return {"updated": updated}


def _online_envs(db: Session, workspace_id: uuid.UUID) -> set[uuid.UUID]:
    at = agent_sessions.now()
    return set(db.scalars(
        select(AgentSession.environment_id).where(AgentSession.workspace_id == workspace_id,
                                                  *agent_sessions.live_filter(at))
    ).all())


@web_router.get("")
def list_devices(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    online = _online_envs(db, auth.workspace_id)
    rows = db.execute(
        scoped(Device, auth.workspace_id)
        .join(Environment, Environment.id == Device.environment_id)
        .add_columns(Environment.name)
        .order_by(Device.unbound_at.is_not(None), Device.created_at)
    ).all()
    return {"items": [_out(d, name, d.environment_id in online) for d, name in rows]}


@web_router.patch("/{device_id}")
def update_device(device_id: uuid.UUID, body: DevicePatch, request: Request, auth: WebAuth = Depends(web_auth),
                  db: Session = Depends(get_db)):
    d = get_owned(db, Device, device_id, auth.workspace_id, for_update=True)
    fields = body.model_fields_set
    if "display_name" in fields:
        d.display_name = (body.display_name or "").strip() or None
    if "expected_account" in fields:
        d.expected_account = body.expected_account
    audit.record(db, request, "device.update", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=d.id)
    db.commit()
    return _out(d, db.get(Environment, d.environment_id).name, d.environment_id in _online_envs(db, auth.workspace_id))


@web_router.post("/{device_id}/unbind")
def unbind(device_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """Release the phone so it can be registered again (here or by its new owner). Idempotent.

    Outstanding scheduled posts for this phone do not exist yet; P4/P5 must handle them here
    explicitly (cancel or reassign with the user's choice) before the phone is released.
    """
    d = get_owned(db, Device, device_id, auth.workspace_id, for_update=True)
    if d.unbound_at is None:
        d.unbound_at = agent_sessions.now()
        audit.record(db, request, "device.unbind", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=d.id)
    db.commit()
    return _out(d, db.get(Environment, d.environment_id).name, False)
