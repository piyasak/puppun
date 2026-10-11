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
from .entitlements import entitlement
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
    clip_ids: tuple[uuid.UUID, ...] | None = None  # only these clips of the job (e.g. "post now", one clip)


def _slot_error(exc: slots.SlotError) -> ApiError:
    return ApiError(422, exc.code, str(exc))


# Why clips were left out, when all of them were left out for the same reason (shown as the error).
EXCLUSION_MESSAGES = {
    "POST_NEEDS_ACTION": "คลิปนี้มีโพสต์ที่ต้องดำเนินการค้างอยู่ — กดลองใหม่หรือยกเลิกรายการนั้นในหน้าตารางโพสต์ก่อน",
    "ALREADY_SCHEDULED": "คลิปนี้ตั้งเวลาโพสต์ไว้แล้ว ดูหรือยกเลิกได้ในหน้าตารางโพสต์",
    "FILE_DELETED": "ไฟล์คลิปนี้ถูกลบจากเครื่อง Agent แล้วหลังโพสต์",
    "CHECKS_FAILED": "คลิปนี้ไม่ผ่านการตรวจไฟล์",
}


def _exclusion(clip: Clip, live: dict[uuid.UUID, str]) -> str | None:
    if clip.agent_file_deleted_at is not None:
        return "FILE_DELETED"  # deleted on the Agent's PC after it was posted (job's delete_after_post)
    if clip.id in live:
        # A post of it that stopped for a person (NEEDS_ACTION / UNKNOWN) still holds the clip: one live post per clip.
        return "POST_NEEDS_ACTION" if live[clip.id] in ("NEEDS_ACTION", "UNKNOWN") else "ALREADY_SCHEDULED"
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
    if req.clip_ids is not None:
        stmt = stmt.where(Clip.id.in_(req.clip_ids))
    job_clips = db.scalars(stmt.with_for_update() if lock else stmt).all()
    live = dict(db.execute(select(ScheduleItem.clip_id, ScheduleItem.state).where(
        ScheduleItem.clip_id.in_([c.id for c in job_clips]),
        ScheduleItem.state.not_in(("CANCELLED", "SKIPPED")))).all()) if job_clips else {}
    eligible, excluded = [], []
    for clip in job_clips:
        reason = _exclusion(clip, live)
        if reason:
            excluded.append({"clip_id": str(clip.id), "index": clip.clip_index, "reason": reason})
        else:
            eligible.append(clip)
    if not eligible:
        reasons = {x["reason"] for x in excluded}
        message = EXCLUSION_MESSAGES.get(reasons.pop()) if len(reasons) == 1 else None
        raise ApiError(409, "NO_APPROVED_CLIPS", message or "ยังไม่มีคลิปที่อนุมัติแล้วให้ตั้งเวลา", {"excluded": excluded})

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


def shift_plan(db: Session, series: ScheduleSeries, from_seq: int, at: datetime, *,
               lock: bool) -> list[tuple[ScheduleItem, datetime]]:
    """Unstarted items from `from_seq` on, with their new times: the first at the next allowed slot
    from `at`, each next one previous slot + X. Never earlier than planned, never all at once
    (offline defer and resume, PRD §G.7/§G.9). Nothing is saved here."""
    tz = slots.zone(series.timezone)
    window = slots.Window(series.window_start_min, series.window_end_min)
    stmt = select(ScheduleItem).where(ScheduleItem.series_id == series.id, ScheduleItem.seq >= from_seq,
                                      ScheduleItem.state.in_(PENDING)).order_by(ScheduleItem.seq)
    out, prev = [], None
    for item in db.scalars(stmt.with_for_update() if lock else stmt).all():
        proposed = slots.normalize(at if prev is None else prev + timedelta(hours=series.interval_hours), window, tz)
        new = max(proposed, item.scheduled_at)
        out.append((item, new))
        prev = new
    return out


def apply_shift(plan: list[tuple[ScheduleItem, datetime]], reason: str, at: datetime) -> int:
    moved = 0
    for item, new in plan:
        if new != item.scheduled_at:
            item.scheduled_at, item.reason = new, reason
            item.state_version += 1
            item.updated_at = at
            moved += 1
    return moved


def _first_missed(db: Session, series: ScheduleSeries, at: datetime) -> int | None:
    return db.scalar(select(ScheduleItem.seq).where(
        ScheduleItem.series_id == series.id, ScheduleItem.state.in_(PENDING), ScheduleItem.scheduled_at < at)
        .order_by(ScheduleItem.seq).limit(1))


def pause(series: ScheduleSeries) -> None:
    if series.state != "ACTIVE":
        raise ApiError(409, "SERIES_NOT_ACTIVE", "ตารางนี้ไม่ได้อยู่ในสถานะใช้งาน", {"state": series.state})
    # Posts already handed to an Agent finish and are followed to a result (FR-19).
    series.state, series.version, series.updated_at = "PAUSED", series.version + 1, now()


def resume_plan(db: Session, series: ScheduleSeries, at: datetime, *, lock: bool) -> list[tuple[ScheduleItem, datetime]]:
    """Posts that fell due during the pause move forward with their spacing; nothing catches up."""
    if series.state != "PAUSED":
        raise ApiError(409, "SERIES_NOT_PAUSED", "ตารางนี้ไม่ได้หยุดชั่วคราว", {"state": series.state})
    first = _first_missed(db, series, at)
    return [] if first is None else shift_plan(db, series, first, at, lock=lock)


def resume(db: Session, series: ScheduleSeries, expected_version: int) -> int:
    if series.version != expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "ตารางถูกเปลี่ยนไปแล้ว ดูตัวอย่างใหม่อีกครั้ง",
                       {"current_version": series.version})
    at = now()
    moved = apply_shift(resume_plan(db, series, at, lock=True), "RESUMED", at)
    series.state, series.version, series.updated_at = "ACTIVE", series.version + 1, at
    return moved


def edit_item(db: Session, item: ScheduleItem, expected_state_version: int, new_local: str) -> None:
    """Move one unstarted post. It stays inside the window, in the future, and in clip order."""
    if item.state not in PENDING:
        raise ApiError(409, "ITEM_NOT_EDITABLE", "รายการนี้เริ่มส่งแล้วหรือจบแล้ว แก้ไม่ได้", {"state": item.state})
    if item.state_version != expected_state_version:
        raise ApiError(409, "VERSION_CONFLICT", "รายการถูกเปลี่ยนไปแล้ว โหลดใหม่ก่อนแก้",
                       {"current_version": item.state_version})
    series = db.get(ScheduleSeries, item.series_id)
    if series.state in ("CANCELLED", "COMPLETED"):
        raise ApiError(409, "SERIES_NOT_ACTIVE", "ตารางนี้จบแล้ว")
    try:
        tz = slots.zone(series.timezone)
        new = slots.parse_local(new_local, tz).astimezone(UTC)
    except slots.SlotError as exc:
        raise _slot_error(exc) from None
    window = slots.Window(series.window_start_min, series.window_end_min)
    if slots.normalize(new, window, tz) != new:
        raise ApiError(422, "OUTSIDE_WINDOW", f"เวลาต้องอยู่ในช่วงที่โพสต์ได้ {window.label()}")
    if new < now() + START_GRACE:
        raise ApiError(422, "START_IN_PAST", "เวลาต้องอยู่ในอนาคต")
    neighbours = db.execute(select(ScheduleItem.seq, ScheduleItem.scheduled_at).where(
        ScheduleItem.series_id == series.id, ScheduleItem.state.not_in(("CANCELLED", "SKIPPED")),
        ScheduleItem.id != item.id)).all()
    if any((seq < item.seq and at >= new) or (seq > item.seq and at <= new) for seq, at in neighbours):
        raise ApiError(422, "ITEM_ORDER", "เวลาใหม่ต้องอยู่ระหว่างโพสต์ก่อนหน้าและถัดไป (คงลำดับคลิป)")
    item.scheduled_at, item.reason = new, "EDITED"
    item.state_version += 1
    item.updated_at = now()


def dispatchable(db: Session, item: ScheduleItem, *, expected_state: str = "SCHEDULED") -> str | None:
    """None when this exact item may be handed to an Agent now; otherwise the reason it may not.

    Checked immediately before dispatch (PRD §G.6, G3-05): the approval must still name the
    bound metadata version and the same file the item was scheduled with.
    """
    if item.state != expected_state:
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
    if clip.agent_file_deleted_at is not None:
        return "FILE_DELETED"
    device = db.get(Device, item.device_id)
    if device.unbound_at is not None:
        return "DEVICE_UNBOUND"
    if not entitlement(db, item.workspace_id).cycle.active:
        return "SUBSCRIPTION_INACTIVE"  # waits (not parked): renewing lets it run under the usual late rules
    return None
