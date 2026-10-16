"""Phone screen diagnostics (PO 2026-10-16): the Agent uploads, owners and platform staff look."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from .. import diagnostics as rules
from ..agent_sessions import AgentContext
from ..deps import StaffAuth, WebAuth, get_db, staff, web_auth
from ..errors import ApiError
from ..models import Device, Diagnostic
from .agent import agent_context

agent_router = APIRouter(prefix="/v1/agent/diagnostics")
web_router = APIRouter(prefix="/v1")
admin_router = APIRouter(prefix="/v1/admin/diagnostics")

LINK_TTL_S = 600


# --- Agent ----------------------------------------------------------------------------------------------

class FailureIn(BaseModel):
    serial: str = Field(max_length=64)
    item_id: uuid.UUID | None = None
    code: str = Field(default="", max_length=40)


class RequestedIn(BaseModel):
    ready_serials: list[str] = Field(default_factory=list, max_length=50)


class DoneIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)
    error: str | None = Field(default=None, max_length=300)


@agent_router.post("", status_code=201)
def agent_failure(body: FailureIn, request: Request, ctx: AgentContext = Depends(agent_context),
                  db: Session = Depends(get_db)):
    rules.purge(db, request.app.state.storage)
    row = rules.failure(db, ctx.environment_id, body.serial, body.item_id, body.code)
    db.commit()
    return {"id": str(row.id)}


@agent_router.post("/requested")
def agent_requested(body: RequestedIn, request: Request, ctx: AgentContext = Depends(agent_context),
                    db: Session = Depends(get_db)):
    """The oldest check asked for on one of these phones, now running; None when there is none."""
    rules.purge(db, request.app.state.storage)
    row = rules.next_requested(db, ctx.environment_id, body.ready_serials)
    db.commit()
    if row is None:
        return {"diagnostic": None}
    serial = db.get(Device, row.device_id).serial
    return {"diagnostic": {"id": str(row.id), "check": row.check, "serial": serial}}


@agent_router.put("/{diag_id}/files/{step}/{filename}")
async def agent_file(diag_id: uuid.UUID, step: int, filename: str, request: Request,
                     ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    name, _, ext = filename.rpartition(".")
    limit = rules.MAX_FILE_BYTES.get(ext)
    if limit is None:
        raise ApiError(422, "VALIDATION_ERROR", "รับเฉพาะ .png และ .xml")
    fd, temp_name = tempfile.mkstemp(prefix="diag-", suffix=f".{ext}")
    temp, size = Path(temp_name), 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise ApiError(413, "FILE_TOO_LARGE", "ไฟล์การตรวจใหญ่เกินกำหนด")
                out.write(chunk)

        def store() -> dict:
            row = rules.agent_row(db, ctx.environment_id, diag_id)
            rules.add_file(row, request.app.state.storage, step, name, ext, temp, size)
            db.commit()
            return {"files": len(row.files)}

        return await run_in_threadpool(store)
    finally:
        temp.unlink(missing_ok=True)


@agent_router.post("/{diag_id}/done")
def agent_done(diag_id: uuid.UUID, body: DoneIn, ctx: AgentContext = Depends(agent_context),
               db: Session = Depends(get_db)):
    row = rules.agent_row(db, ctx.environment_id, diag_id)
    rules.finish(row, body.note, body.error)
    db.commit()
    return {"status": row.status}


# --- web: the Workspace's own phones ---------------------------------------------------------------------

class CheckIn(BaseModel):
    check: str = Field(max_length=40)


def _owned_device(db: Session, auth: WebAuth, device_id: uuid.UUID) -> Device:
    device = db.scalars(select(Device).where(Device.id == device_id, Device.workspace_id == auth.workspace_id)).first()
    if device is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโทรศัพท์นี้")
    return device


@web_router.get("/diagnostics/checks")
def checks(auth: WebAuth = Depends(web_auth)):
    return {"items": [{"check": k, "label": v} for k, v in rules.CHECKS.items()], "keep_days": rules.KEEP_DAYS}


@web_router.post("/devices/{device_id}/diagnostics", status_code=201)
def request_check(device_id: uuid.UUID, body: CheckIn, request: Request, auth: WebAuth = Depends(web_auth),
                  db: Session = Depends(get_db)):
    rules.purge(db, request.app.state.storage)
    device = _owned_device(db, auth, device_id)
    row = rules.request(db, auth.workspace_id, device.id, body.check, auth.user_id)
    audit.record(db, request, "diagnostic.request", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=row.id, details={"device_id": str(device.id), "check": body.check})
    db.commit()
    return rules.out(row)


@web_router.get("/devices/{device_id}/diagnostics")
def list_for_device(device_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                    db: Session = Depends(get_db)):
    rules.purge(db, request.app.state.storage)
    device = _owned_device(db, auth, device_id)
    db.commit()
    rows = db.scalars(select(Diagnostic).where(Diagnostic.device_id == device.id, Diagnostic.expires_at > rules.now())
                      .order_by(Diagnostic.created_at.desc()).limit(30)).all()
    return {"items": [rules.out(r) for r in rows], "keep_days": rules.KEEP_DAYS}


@web_router.get("/diagnostics/{diag_id}")
def view(diag_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    row = db.scalars(select(Diagnostic).where(Diagnostic.id == diag_id, Diagnostic.workspace_id == auth.workspace_id,
                                              Diagnostic.expires_at > rules.now())).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบการตรวจนี้")
    audit.record(db, request, "diagnostic.view", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=row.id)
    db.commit()
    return rules.out(row, request.app.state.storage, LINK_TTL_S)


# --- platform staff ---------------------------------------------------------------------------------------

@admin_router.get("")
def admin_list(request: Request, workspace_id: uuid.UUID | None = None, who: StaffAuth = Depends(staff),
               db: Session = Depends(get_db)):
    rules.purge(db, request.app.state.storage)
    db.commit()
    stmt = select(Diagnostic).where(Diagnostic.expires_at > rules.now())
    if workspace_id:
        stmt = stmt.where(Diagnostic.workspace_id == workspace_id)
    rows = db.scalars(stmt.order_by(Diagnostic.created_at.desc()).limit(50)).all()
    return {"items": [rules.out(r) | {"workspace_id": str(r.workspace_id)} for r in rows]}


@admin_router.get("/{diag_id}")
def admin_view(diag_id: uuid.UUID, request: Request, who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    row = db.scalars(select(Diagnostic).where(Diagnostic.id == diag_id, Diagnostic.expires_at > rules.now())).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบการตรวจนี้")
    audit.record(db, request, "admin.diagnostic.view", workspace_id=row.workspace_id, actor_user_id=who.user_id,
                 target_id=row.id)
    db.commit()
    return rules.out(row, request.app.state.storage, LINK_TTL_S) | {"workspace_id": str(row.workspace_id)}
