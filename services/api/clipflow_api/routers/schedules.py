"""Schedules: server-calculated preview, create/list/detail, cancel (P4.1/P4.2)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, schedules, slots
from ..deps import WebAuth, get_db, web_auth
from ..models import Clip, Device, ScheduleItem, ScheduleSeries
from ..tenancy import get_owned, scoped

web_router = APIRouter(prefix="/v1/schedules")
items_router = APIRouter(prefix="/v1/schedule-items")


class ScheduleIn(BaseModel):
    job_id: uuid.UUID
    device_id: uuid.UUID
    start_local: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    timezone: str = "Asia/Bangkok"
    window_start: str = Field(default="09:00", pattern=r"^\d{1,2}:\d{2}$")
    window_end: str = Field(default="21:00", pattern=r"^\d{1,2}:\d{2}$")
    interval_hours: int = Field(ge=1, le=slots.MAX_INTERVAL_HOURS)
    offline_policy: Literal["defer", "skip"] = "defer"

    def request(self) -> schedules.Request:
        return schedules.Request(**self.model_dump())


class CreateIn(ScheduleIn):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


def item_out(item: ScheduleItem, clip_index: int | None = None) -> dict:
    return {
        "id": str(item.id), "series_id": str(item.series_id), "seq": item.seq, "clip_id": str(item.clip_id),
        "clip_index": clip_index, "device_id": str(item.device_id), "state": item.state, "reason": item.reason,
        "state_version": item.state_version, "metadata_version": item.metadata_version,
        "clip_sha256": item.clip_sha256, "scheduled_at": item.scheduled_at.isoformat(),
        # Kept apart on purpose: the plan versus what actually happened (PRD §G.8, G4-05).
        "claimed_at": item.claimed_at.isoformat() if item.claimed_at else None,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
    }


def series_out(db: Session, s: ScheduleSeries, *, with_items: bool = False) -> dict:
    device = db.get(Device, s.device_id)
    out = {
        "id": str(s.id), "job_id": str(s.job_id), "state": s.state, "version": s.version,
        "device": {"id": str(device.id), "name": device.display_name or device.model, "account": device.expected_account},
        "timezone": s.timezone, "window": slots.Window(s.window_start_min, s.window_end_min).label(),
        "interval_hours": s.interval_hours, "offline_policy": s.offline_policy, "start_at": s.start_at.isoformat(),
        "created_at": s.created_at.isoformat(),
    }
    rows = db.execute(select(ScheduleItem, Clip.clip_index).join(Clip, Clip.id == ScheduleItem.clip_id)
                      .where(ScheduleItem.series_id == s.id).order_by(ScheduleItem.seq)).all()
    out["counts"] = {}
    for item, _ in rows:
        out["counts"][item.state] = out["counts"].get(item.state, 0) + 1
    if with_items:
        out["items"] = [item_out(item, idx) for item, idx in rows]
    return out


@web_router.post("/preview")
def preview(body: ScheduleIn, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return schedules.public(schedules.build(db, auth.workspace_id, body.request(), lock=False))


@web_router.post("")
def create(body: CreateIn, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    req = schedules.Request(**body.model_dump(exclude={"idempotency_key"}))
    series, created = schedules.create(db, auth.workspace_id, auth.user_id, body.idempotency_key, req)
    if created:
        audit.record(db, request, "schedule.create", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=series.id)
    db.commit()
    return JSONResponse(series_out(db, series, with_items=True), status_code=201 if created else 200)


@web_router.get("")
def list_series(job_id: uuid.UUID | None = None, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    stmt = scoped(ScheduleSeries, auth.workspace_id).order_by(ScheduleSeries.created_at.desc()).limit(100)
    if job_id:
        stmt = stmt.where(ScheduleSeries.job_id == job_id)
    return {"items": [series_out(db, s, with_items=True) for s in db.scalars(stmt).all()]}


@web_router.get("/{series_id}")
def get_series(series_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return series_out(db, get_owned(db, ScheduleSeries, series_id, auth.workspace_id), with_items=True)


@web_router.post("/{series_id}/cancel")
def cancel_series(series_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                  db: Session = Depends(get_db)):
    series = get_owned(db, ScheduleSeries, series_id, auth.workspace_id, for_update=True)
    schedules.cancel_series(db, series)
    audit.record(db, request, "schedule.cancel", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=series.id)
    db.commit()
    return series_out(db, series, with_items=True)


@items_router.post("/{item_id}/cancel")
def cancel_item(item_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                db: Session = Depends(get_db)):
    item = get_owned(db, ScheduleItem, item_id, auth.workspace_id, for_update=True)
    schedules.cancel_item(item)
    audit.record(db, request, "schedule_item.cancel", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=item.id)
    db.commit()
    return item_out(item)
