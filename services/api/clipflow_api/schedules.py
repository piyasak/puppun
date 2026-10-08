"""Schedule series and items (P4.1/P4.2, FR-09..FR-11, G3-05, PRD §5/§G).

- Only clips whose *current* version is approved are scheduled. Each item binds the exact
  metadata version and file hash it may post (PRD §F), never "the latest".
- When a clip's approval changes, its unstarted items follow: an approved current version
  rebinds the item; anything else parks it in NEEDS_ACTION (APPROVAL_CHANGED). `dispatchable`
  re-checks everything right before a post is handed to an Agent.
- Creating a series locks the phone row, then the job's clips, so concurrent series on one phone
  see each other's items (collision preview) and one clip never lands in two live items.
- Same-phone collisions are not refused (Q-05): the preview shows when each post is expected to
  start once the phone is free, assuming one post occupies the phone for POST_SLOT (E-39).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clips as clip_rules
from . import slots
from .errors import ApiError
from .models import Clip, Device, Job, ScheduleItem, ScheduleSeries
from .tenancy import get_owned

POST_SLOT = timedelta(minutes=15)  # estimated phone time per post, for queue/collision preview (E-39)
PENDING = ("SCHEDULED", "NEEDS_ACTION")  # not started: may still be edited, cancelled or rebound
START_GRACE = timedelta(minutes=1)


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Request:
    job_id: uuid.UUID
    device_id: uuid.UUID
    start_local: str  # 'YYYY-MM-DDTHH:MM' in `timezone`
    timezone: str
    window_start: str  # 'HH:MM'
    window_end: str  # 'HH:MM' or '24:00'
    interval_hours: int
    offline_policy: str  # defer | skip


def _slot_error(exc: slots.SlotError) -> ApiError:
    return ApiError(422, exc.code, str(exc))


def _exclusion(clip: Clip, live: set[uuid.UUID]) -> str | None:
    if clip.id in live:
        return "ALREADY_SCHEDULED"
    if clip.uploaded_at is None:
        return "NOT_UPLOADED"
    if clip.check_status == "failed":
        return "CHECKS_FAILED"
    if not clip_rules.is_approved(clip):
        return "NOT_APPROVED"
    return None


def _local(at: datetime, tz) -> str:
    return at.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def build(db: Session, workspace_id: uuid.UUID, req: Request, *, lock: bool) -> dict:
    """Validate and calculate a series without saving it (the preview, PRD §G.5)."""
    try:
        tz = slots.zone(req.timezone)
        window = slots.Window.parse(req.window_start, req.window_end)
        slots.check_interval(req.interval_hours)
        start = slots.parse_local(req.start_local, tz)
    except slots.SlotError as exc:
        raise _slot_error(exc) from None
    if req.offline_policy not in ("defer", "skip"):
        raise ApiError(422, "VALIDATION_ERROR", "นโยบายเมื่อเครื่องออฟไลน์ต้องเป็น defer หรือ skip")
    if start < now() - START_GRACE:
        raise ApiError(422, "START_IN_PAST", "เวลาเริ่มต้องไม่อยู่ในอดีต")

    job = get_owned(db, Job, req.job_id, workspace_id)
    if job.state == "CANCELLED":
        raise ApiError(409, "JOB_NOT_ACTIVE", "งานนี้ถูกยกเลิกแล้ว")
    device = get_owned(db, Device, req.device_id, workspace_id, for_update=lock)
    if device.unbound_at is not None:
        raise ApiError(409, "DEVICE_UNBOUND", "โทรศัพท์นี้ยกเลิกการผูกแล้ว")
    if device.environment_id != job.environment_id:
        # The Agent that made the clips keeps the files and posts them (Q-15).
        raise ApiError(409, "DEVICE_OTHER_ENVIRONMENT", "โทรศัพท์ต้องอยู่ใน Environment เดียวกับงานที่ผลิตคลิป")
    if not device.expected_account:
        raise ApiError(409, "DEVICE_NEEDS_DETAILS", "ใส่บัญชี TikTok ของโทรศัพท์นี้ก่อน (หน้าโทรศัพท์)")

    stmt = select(Clip).where(Clip.job_id == job.id).order_by(Clip.clip_index)
    job_clips = db.scalars(stmt.with_for_update() if lock else stmt).all()
    live = set(db.scalars(select(ScheduleItem.clip_id).where(
        ScheduleItem.clip_id.in_([c.id for c in job_clips]),
        ScheduleItem.state.not_in(("CANCELLED", "SKIPPED")))).all()) if job_clips else set()
    eligible, excluded = [], []
    for clip in job_clips:
        reason = _exclusion(clip, live)
        if reason:
            excluded.append({"clip_id": str(clip.id), "index": clip.clip_index, "reason": reason})
        else:
            eligible.append(clip)
    if not eligible:
        raise ApiError(409, "NO_APPROVED_CLIPS", "ยังไม่มีคลิปที่อนุมัติแล้วให้ตั้งเวลา", {"excluded": excluded})

    times = slots.plan(start, len(eligible), req.interval_hours, window, tz)

    # Expected start per post on this phone: one at a time, queued behind earlier posts (Q-05).
    others = db.execute(select(ScheduleItem.id, ScheduleItem.scheduled_at).where(
        ScheduleItem.device_id == device.id, ScheduleItem.state.in_(PENDING))).all()
    # At equal times, posts already scheduled keep their place ahead of the new series.
    queue = sorted([(t, 0, oid) for oid, t in others] + [(t, 1, i) for i, t in enumerate(times)],
                   key=lambda q: (q[0], q[1]))
    expected, free_at = {}, None
    for at, rank, key in queue:
        kind = "new" if rank else "other"
        begin = at if free_at is None or at >= free_at else free_at
        if kind == "new":
            expected[key] = begin
        free_at = begin + POST_SLOT
    items = []
    for i, (clip, at) in enumerate(zip(eligible, times, strict=True)):
        clash = [str(oid) for oid, t in others if abs(t - at) < POST_SLOT]
        items.append({
            "seq": i + 1, "clip_id": str(clip.id), "clip_index": clip.clip_index,
            "metadata_version": clip.metadata_version, "clip_sha256": clip.render_sha256,
            "scheduled_at": at.isoformat(), "scheduled_local": _local(at, tz),
            "expected_start": expected[i].isoformat(), "expected_start_local": _local(expected[i], tz),
            "collides_with": clash,
        })
    return {
        "job_id": str(job.id), "device": {"id": str(device.id), "name": device.display_name or device.model,
                                          "account": device.expected_account},
        "timezone": req.timezone, "window": window.label(), "interval_hours": req.interval_hours,
        "offline_policy": req.offline_policy, "start_at": start.astimezone(UTC).isoformat(),
        "items": items, "excluded": excluded, "collisions": sum(1 for it in items if it["collides_with"]),
        "_window": window, "_eligible": eligible, "_times": times,
    }


def public(preview: dict) -> dict:
    return {k: v for k, v in preview.items() if not k.startswith("_")}


def create(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, idempotency_key: str,
           req: Request) -> tuple[ScheduleSeries, bool]:
    existing = db.scalars(select(ScheduleSeries).where(ScheduleSeries.workspace_id == workspace_id,
                                                       ScheduleSeries.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing, False
    p = build(db, workspace_id, req, lock=True)  # validation reruns under the phone/clip locks (PRD §G.5)
    at = now()
    series = ScheduleSeries(
        workspace_id=workspace_id, job_id=req.job_id, device_id=req.device_id, idempotency_key=idempotency_key,
        timezone=req.timezone, window_start_min=p["_window"].start_min, window_end_min=p["_window"].end_min,
        interval_hours=req.interval_hours, start_at=datetime.fromisoformat(p["start_at"]),
        offline_policy=req.offline_policy, state="ACTIVE", version=1, created_by=user_id,
        created_at=at, updated_at=at,
    )
    db.add(series)
    db.flush()
    for i, (clip, when) in enumerate(zip(p["_eligible"], p["_times"], strict=True)):
        db.add(ScheduleItem(
            workspace_id=workspace_id, series_id=series.id, clip_id=clip.id, device_id=req.device_id, seq=i + 1,
            scheduled_at=when, metadata_version=clip.approved_metadata_version, clip_sha256=clip.approved_sha256,
            state="SCHEDULED", state_version=1, created_at=at, updated_at=at,
        ))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "CLIP_ALREADY_SCHEDULED", "มีคลิปที่ถูกตั้งเวลาไว้แล้ว ลองดูตัวอย่างใหม่") from None
    return series, True


def _set(item: ScheduleItem, state: str, reason: str | None) -> None:
    item.state, item.reason = state, reason
    item.state_version += 1
    item.updated_at = now()


def cancel_series(db: Session, series: ScheduleSeries) -> int:
    if series.state in ("CANCELLED", "COMPLETED"):
        raise ApiError(409, "SERIES_NOT_ACTIVE", "ตารางนี้จบแล้ว")
    items = db.scalars(select(ScheduleItem).where(ScheduleItem.series_id == series.id,
                                                  ScheduleItem.state.in_(PENDING)).with_for_update()).all()
    for item in items:
        _set(item, "CANCELLED", "SERIES_CANCELLED")
    series.state, series.version, series.updated_at = "CANCELLED", series.version + 1, now()
    return len(items)


def cancel_item(item: ScheduleItem) -> None:
    if item.state not in PENDING:
        # Started posts cannot be pulled back here; they are followed to a result (FR-19).
        raise ApiError(409, "ITEM_NOT_CANCELLABLE", "รายการนี้เริ่มส่งแล้วหรือจบแล้ว ยกเลิกไม่ได้",
                       {"state": item.state})
    _set(item, "CANCELLED", "USER_CANCELLED")


def sync_clip_items(db: Session, clip: Clip) -> int:
    """After an approval change: rebind unstarted items to the newly approved version, or park them."""
    items = db.scalars(select(ScheduleItem).where(ScheduleItem.clip_id == clip.id,
                                                  ScheduleItem.state.in_(PENDING)).with_for_update()).all()
    changed = 0
    for item in items:
        if clip_rules.is_approved(clip):
            bound = (item.metadata_version, item.clip_sha256) == (clip.approved_metadata_version, clip.approved_sha256)
            if not bound or (item.state == "NEEDS_ACTION" and item.reason == "APPROVAL_CHANGED"):
                item.metadata_version, item.clip_sha256 = clip.approved_metadata_version, clip.approved_sha256
                _set(item, "SCHEDULED", None)
                changed += 1
        elif item.state == "SCHEDULED":
            _set(item, "NEEDS_ACTION", "APPROVAL_CHANGED")
            changed += 1
    return changed


def park_device_items(db: Session, device_id: uuid.UUID, reason: str) -> int:
    items = db.scalars(select(ScheduleItem).where(ScheduleItem.device_id == device_id,
                                                  ScheduleItem.state == "SCHEDULED").with_for_update()).all()
    for item in items:
        _set(item, "NEEDS_ACTION", reason)
    return len(items)


def dispatchable(db: Session, item: ScheduleItem) -> str | None:
    """None when this exact item may be handed to an Agent now; otherwise the reason it may not.

    Checked immediately before dispatch (PRD §G.6, G3-05): the approval must still name the
    bound metadata version and the same file the item was scheduled with.
    """
    if item.state != "SCHEDULED":
        return "NOT_SCHEDULED"
    series = db.get(ScheduleSeries, item.series_id)
    if series.state != "ACTIVE":
        return "SERIES_NOT_ACTIVE"
    clip = db.get(Clip, item.clip_id)
    job = db.get(Job, clip.job_id)
    if job.state == "CANCELLED":
        return "JOB_CANCELLED"
    if not clip_rules.is_approved(clip):
        return "NOT_APPROVED"
    if (clip.approved_metadata_version, clip.approved_sha256) != (item.metadata_version, item.clip_sha256):
        return "APPROVAL_CHANGED"
    if clip.render_sha256 != item.clip_sha256 or clip.check_status == "failed":
        return "FILE_CHANGED"
    device = db.get(Device, item.device_id)
    if device.unbound_at is not None:
        return "DEVICE_UNBOUND"
    return None
