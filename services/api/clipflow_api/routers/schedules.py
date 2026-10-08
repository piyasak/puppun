"""Schedules: server-calculated preview, create/list/detail, cancel (P4.1/P4.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, posts, schedules, slots
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import Clip, Device, Job, ScheduleItem, ScheduleSeries
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


class ResumeIn(BaseModel):
    expected_version: int = Field(ge=1)


class ItemPatch(BaseModel):
    expected_state_version: int = Field(ge=1)
    scheduled_local: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class ResolveIn(BaseModel):
    decision: Literal["found_published", "confirmed_not_published", "still_unknown"]
    evidence: str = Field(max_length=500)
    expected_state_version: int = Field(ge=1)


class RetryIn(BaseModel):
    expected_state_version: int = Field(ge=1)


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
        "attempts": item.attempts, "evidence": item.evidence,
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


@web_router.post("/{series_id}/pause")
def pause_series(series_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    series = get_owned(db, ScheduleSeries, series_id, auth.workspace_id, for_update=True)
    schedules.pause(series)
    audit.record(db, request, "schedule.pause", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=series.id)
    db.commit()
    return series_out(db, series, with_items=True)


@web_router.post("/{series_id}/resume/preview")
def resume_preview(series_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """What resuming now would do, calculated on the server (PRD §E: preview before confirm)."""
    series = get_owned(db, ScheduleSeries, series_id, auth.workspace_id)
    plan = schedules.resume_plan(db, series, schedules.now(), lock=False)
    tz = slots.zone(series.timezone)
    return {
        "series_version": series.version,
        "moves": [{"item_id": str(item.id), "seq": item.seq, "from": item.scheduled_at.isoformat(),
                   "to": new.isoformat(), "to_local": new.astimezone(tz).strftime("%Y-%m-%dT%H:%M")}
                  for item, new in plan if new != item.scheduled_at],
    }


@web_router.post("/{series_id}/resume")
def resume_series(series_id: uuid.UUID, body: ResumeIn, request: Request, auth: WebAuth = Depends(web_auth),
                  db: Session = Depends(get_db)):
    series = get_owned(db, ScheduleSeries, series_id, auth.workspace_id, for_update=True)
    schedules.resume(db, series, body.expected_version)
    audit.record(db, request, "schedule.resume", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=series.id)
    db.commit()
    return series_out(db, series, with_items=True)


@items_router.patch("/{item_id}")
def edit_item(item_id: uuid.UUID, body: ItemPatch, request: Request, auth: WebAuth = Depends(web_auth),
              db: Session = Depends(get_db)):
    item = get_owned(db, ScheduleItem, item_id, auth.workspace_id, for_update=True)
    schedules.edit_item(db, item, body.expected_state_version, body.scheduled_local)
    audit.record(db, request, "schedule_item.edit", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=item.id)
    db.commit()
    return item_out(item)


@items_router.get("")
def list_items(start: datetime | None = None, end: datetime | None = None, attention: bool = False,
               auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """Posts in [start, end) across all series: the calendar (P4.6). Scheduled and actual times
    are returned separately; `queued_behind` tells why a post on a busy phone starts later (Q-05).
    `attention=true` instead lists every post waiting for a person (NEEDS_ACTION, UNKNOWN), any date (P5.7)."""
    if attention:
        where = [ScheduleItem.workspace_id == auth.workspace_id, ScheduleItem.state.in_(("NEEDS_ACTION", "UNKNOWN"))]
    else:
        if start is None or end is None or end <= start or end - start > timedelta(days=42):
            raise ApiError(422, "RANGE_INVALID", "ช่วงวันที่ต้องไม่เกิน 6 สัปดาห์")
        where = [ScheduleItem.workspace_id == auth.workspace_id, ScheduleItem.scheduled_at >= start,
                 ScheduleItem.scheduled_at < end]
    rows = db.execute(
        select(ScheduleItem, Clip.clip_index, Job.id, Job.source_url, Job.source_label, ScheduleSeries.timezone,
               ScheduleSeries.state, Device.display_name, Device.model, Device.expected_account)
        .join(Clip, Clip.id == ScheduleItem.clip_id).join(Job, Job.id == Clip.job_id)
        .join(ScheduleSeries, ScheduleSeries.id == ScheduleItem.series_id)
        .join(Device, Device.id == ScheduleItem.device_id)
        .where(*where)
        .order_by(ScheduleItem.scheduled_at, ScheduleItem.created_at, ScheduleItem.seq).limit(1000)).all()
    out, last_on_phone = [], {}
    for item, clip_index, job_id, url, label, tz, series_state, dname, model, account in rows:
        busy_until = last_on_phone.get(item.device_id)
        queued = busy_until is not None and item.state in schedules.PENDING and item.scheduled_at < busy_until
        if item.state not in ("CANCELLED", "SKIPPED"):
            begin = max(item.scheduled_at, busy_until) if busy_until else item.scheduled_at
            last_on_phone[item.device_id] = begin + schedules.POST_SLOT
        out.append(item_out(item, clip_index) | {
            "job": {"id": str(job_id), "source": url or label}, "timezone": tz, "series_state": series_state,
            "device_name": dname or model, "account": account,
            "queued_behind": queued,
            "delay_s": round((item.claimed_at - item.scheduled_at).total_seconds()) if item.claimed_at else None,
        })
    return {"items": out}


@items_router.post("/{item_id}/resolve")
def resolve_item(item_id: uuid.UUID, body: ResolveIn, request: Request, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    """Audited reconciliation of an UNKNOWN post (PRD §E /publish-attempts/{id}/resolve, §H)."""
    item = get_owned(db, ScheduleItem, item_id, auth.workspace_id, for_update=True)
    posts.resolve(db, item, decision=body.decision, evidence=body.evidence, actor=auth.user_id,
                  expected_state_version=body.expected_state_version)
    audit.record(db, request, f"schedule_item.resolve.{body.decision}", workspace_id=auth.workspace_id,
                 actor_user_id=auth.user_id, target_id=item.id)
    db.commit()
    return item_out(item)


@items_router.post("/{item_id}/retry")
def retry_item(item_id: uuid.UUID, body: RetryIn, request: Request, auth: WebAuth = Depends(web_auth),
               db: Session = Depends(get_db)):
    item = get_owned(db, ScheduleItem, item_id, auth.workspace_id, for_update=True)
    posts.retry(db, item, body.expected_state_version)
    audit.record(db, request, "schedule_item.retry", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=item.id)
    db.commit()
    return item_out(item)
