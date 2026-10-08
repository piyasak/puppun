"""Handing scheduled posts to Agents (P4.3, E-40; PRD §G.6–§G.9, §H).

Claim (`POST /v1/agent/posts/claim`):
1. Expire leases: an Agent lost before Submit gives the post back (redelivered later, at most
   MAX_ATTEMPTS times); lost after Submit, the post becomes UNKNOWN and is never retried.
2. Late posts never fire in a burst: items more than LATENESS past their slot get the series'
   offline policy first, defer (this and later items move forward, spacing kept) or skip.
3. Due items on phones this Agent reports ready are tried oldest first. Each phone row is locked
   (SKIP LOCKED), and a phone that has a post in flight, or an UNKNOWN one, is busy: one post
   per phone at a time, two Agents never get the same item (G4-03).
4. `schedules.dispatchable` runs right before the hand-over; a refused item is parked.

Events (`POST /v1/agent/posts/{id}/events`) move the post along
CLAIMED → TRANSFERRING → PREPARING → (DRY_RUN_DONE | SUBMITTING → VERIFYING → VERIFIED_SUCCESS / UNKNOWN).
Only the lease holder may report; ids are deduplicated. SUBMITTING is refused unless the server
runs in live mode, which no deployed server can (app.create_app), and it re-checks approval
first (§G.6 "again before submission"). Success needs evidence (§H).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from . import devices as device_rules
from . import schedules
from .agent_sessions import AgentContext
from .errors import ApiError
from .models import Clip, ClipMetadata, Device, ScheduleItem, ScheduleItemEvent, ScheduleSeries

LEASE_S = 300
MAX_ATTEMPTS = 3
LATENESS = timedelta(minutes=60)  # later than this, a post is "missed": offline policy, not catch-up
BEFORE_SUBMIT = ("CLAIMED", "TRANSFERRING", "PREPARING")
AFTER_SUBMIT = ("SUBMITTING", "VERIFYING")
IN_FLIGHT = BEFORE_SUBMIT + AFTER_SUBMIT
BUSY = IN_FLIGHT + ("UNKNOWN",)  # an unresolved post may still be uploading on that phone
FINAL = ("VERIFIED_SUCCESS", "DRY_RUN_DONE", "CANCELLED", "SKIPPED")
ORDER = {"CLAIMED": 0, "TRANSFERRING": 1, "PREPARING": 2, "SUBMITTING": 3, "VERIFYING": 4}
EVIDENCE_METHODS = ("caption_marker", "platform_post_id", "post_url")


def now() -> datetime:
    return datetime.now(UTC)


def _move(item: ScheduleItem, state: str, reason: str | None, at: datetime) -> None:
    item.state, item.reason = state, reason
    item.state_version += 1
    item.updated_at = at


def _release(item: ScheduleItem) -> None:
    item.lease_session_id, item.lease_expires_at = None, None


def _maybe_complete(db: Session, series_id: uuid.UUID, at: datetime) -> None:
    series = db.get(ScheduleSeries, series_id)
    if series.state != "ACTIVE":
        return
    open_items = db.scalar(select(exists().where(ScheduleItem.series_id == series_id,
                                                 ScheduleItem.state.not_in(FINAL))))
    if not open_items:
        series.state, series.version, series.updated_at = "COMPLETED", series.version + 1, at


# --- claim ------------------------------------------------------------------------------------

def expire_leases(db: Session, environment_id: uuid.UUID, at: datetime) -> None:
    stale = db.scalars(select(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id).where(
        Device.environment_id == environment_id, ScheduleItem.state.in_(IN_FLIGHT),
        ScheduleItem.lease_expires_at < at).with_for_update(of=ScheduleItem, skip_locked=True)).all()
    for item in stale:
        _release(item)
        if item.state in AFTER_SUBMIT:
            _move(item, "UNKNOWN", "AGENT_LOST_AFTER_SUBMIT", at)  # never replayed (§G, FR-18)
        elif item.attempts >= MAX_ATTEMPTS:
            _move(item, "NEEDS_ACTION", "AGENT_LOST", at)
        else:
            _move(item, "SCHEDULED", "REDELIVERY", at)


def apply_offline_policy(db: Session, environment_id: uuid.UUID, at: datetime) -> None:
    """Missed posts: skip them, or move the series forward keeping its spacing (Q-06, §G.7)."""
    missed = db.scalars(select(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id).where(
        Device.environment_id == environment_id, ScheduleItem.state == "SCHEDULED",
        ScheduleItem.scheduled_at < at - LATENESS).order_by(ScheduleItem.scheduled_at)
        .with_for_update(of=ScheduleItem, skip_locked=True)).all()
    done: set[uuid.UUID] = set()
    for item in missed:
        if item.series_id in done:
            continue
        series = db.get(ScheduleSeries, item.series_id)
        if series.state != "ACTIVE":
            continue
        if series.offline_policy == "skip":
            _move(item, "SKIPPED", "MISSED_SLOT", at)
            _maybe_complete(db, series.id, at)
            continue
        defer_series(db, series, item.seq, at)
        done.add(series.id)


def defer_series(db: Session, series: ScheduleSeries, from_seq: int, at: datetime) -> None:
    schedules.apply_shift(schedules.shift_plan(db, series, from_seq, at, lock=True), "DEFERRED", at)


def _busy(db: Session, device_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists().where(ScheduleItem.device_id == device_id,
                                                ScheduleItem.state.in_(BUSY)))))


def claim(db: Session, ctx: AgentContext, ready_serials: list[str]) -> ScheduleItem | None:
    at = now()
    expire_leases(db, ctx.environment_id, at)
    apply_offline_policy(db, ctx.environment_id, at)
    keys = set()
    for raw in ready_serials[:50]:
        try:
            keys.add(device_rules.normalize_serial(raw)[1])
        except ApiError:
            continue  # Wi-Fi ADB addresses and junk never match a registered phone
    if not keys:
        return None
    due = db.scalars(select(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id).where(
        Device.environment_id == ctx.environment_id, Device.unbound_at.is_(None), Device.serial_key.in_(keys),
        ScheduleItem.state == "SCHEDULED", ScheduleItem.scheduled_at <= at,
    ).order_by(ScheduleItem.scheduled_at, ScheduleItem.seq).limit(50)
        .with_for_update(of=ScheduleItem, skip_locked=True)).all()
    tried: set[uuid.UUID] = set()
    for item in due:
        if item.device_id in tried:
            continue  # one post per phone per claim; the next waits for this one (Q-05)
        tried.add(item.device_id)
        phone = db.scalars(select(Device).where(Device.id == item.device_id)
                           .with_for_update(skip_locked=True)).first()
        if phone is None or _busy(db, phone.id):
            continue
        reason = schedules.dispatchable(db, item)
        if reason == "SERIES_NOT_ACTIVE":
            continue  # paused: waits, keeps its slot rules
        if reason:
            _move(item, "NEEDS_ACTION", reason, at)
            continue
        item.attempts += 1
        item.lease_session_id, item.lease_expires_at = ctx.session_id, at + timedelta(seconds=LEASE_S)
        item.claimed_at = item.claimed_at or at
        _move(item, "CLAIMED", None, at)
        return item
    return None


def spec(db: Session, item: ScheduleItem, storage, ttl_s: int, posting_mode: str) -> dict:
    """What the Agent needs for one post: the bound file and text, the phone and account."""
    clip = db.get(Clip, item.clip_id)
    meta = db.scalars(select(ClipMetadata).where(ClipMetadata.clip_id == clip.id,
                                                 ClipMetadata.version == item.metadata_version)).one()
    phone = db.get(Device, item.device_id)
    return {
        "id": str(item.id), "state": item.state, "state_version": item.state_version, "attempt": item.attempts,
        "posting_mode": posting_mode, "scheduled_at": item.scheduled_at.isoformat(),
        "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None,
        "device": {"serial": phone.serial, "expected_account": phone.expected_account},
        "clip": {"id": str(clip.id), "job_id": str(clip.job_id), "index": clip.clip_index,
                 "sha256": item.clip_sha256, "size_bytes": clip.size_bytes,
                 # The Agent prefers its own copy when the hash matches; otherwise it downloads (FR-17).
                 "download_url": storage.preview_url(clip.storage_key, ttl_s) if clip.storage_key else None},
        "text": {"metadata_version": meta.version, "caption": meta.caption, "hashtags": meta.hashtags},
    }


# --- events -----------------------------------------------------------------------------------

def _bad(item: ScheduleItem, kind: str) -> ApiError:
    return ApiError(409, "BAD_EVENT_ORDER", "event นี้มาผิดลำดับ", {"state": item.state, "type": kind})


def apply_event(db: Session, ctx: AgentContext, item_id: uuid.UUID, event: dict,
                posting_mode: str) -> tuple[ScheduleItem, bool, ApiError | None]:
    """Returns (item, duplicate, refusal). A refusal is raised by the caller *after* committing,
    so the parked state it caused is kept."""
    item = db.scalars(select(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id).where(
        ScheduleItem.id == item_id, Device.environment_id == ctx.environment_id)
        .with_for_update(of=ScheduleItem)).first()
    if item is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบรายการนี้")
    event_id, kind = event["event_id"], event["type"]
    if db.scalars(select(ScheduleItemEvent).where(ScheduleItemEvent.item_id == item.id,
                                                  ScheduleItemEvent.event_id == event_id)).first():
        return item, True, None
    at = now()
    refusal = None
    if item.state not in IN_FLIGHT:
        raise ApiError(409, "ITEM_NOT_ACTIVE", "รายการนี้ไม่ได้อยู่ระหว่างโพสต์แล้ว หยุดงานนี้", {"state": item.state})
    if item.lease_session_id != ctx.session_id or item.lease_expires_at is None or item.lease_expires_at <= at:
        raise ApiError(409, "LEASE_LOST", "รายการนี้ไม่ได้อยู่กับ Agent นี้แล้ว หยุดงานนี้")

    if kind in ("TRANSFERRING", "PREPARING"):
        if ORDER[kind] != ORDER[item.state] + 1:
            raise _bad(item, kind)
        if kind == "TRANSFERRING":
            item.started_at = at
        _move(item, kind, None, at)
    elif kind == "DRY_RUN_DONE":
        if item.state != "PREPARING" or posting_mode != "dry_run":
            raise _bad(item, kind)
        _release(item)
        _move(item, "DRY_RUN_DONE", "STOPPED_BEFORE_SUBMIT", at)
    elif kind == "SUBMITTING":
        if item.state != "PREPARING":
            raise _bad(item, kind)
        if posting_mode != "live":
            raise ApiError(409, "POSTING_DISABLED", "ระบบนี้ยังไม่เปิดการโพสต์จริง (dry-run) หยุดก่อนกดโพสต์")
        reason = schedules.dispatchable(db, item, expected_state="PREPARING")
        if reason:
            _release(item)
            _move(item, "NEEDS_ACTION", reason, at)
            event["detail"] = f"refused: {reason}"
            refusal = ApiError(409, "DISPATCH_REVOKED", "คลิปหรือข้อความเปลี่ยนไปแล้ว ห้ามกดโพสต์", {"reason": reason})
        else:
            item.submitted_at = at
            _move(item, "SUBMITTING", None, at)
    elif kind == "VERIFYING":
        if item.state != "SUBMITTING":
            raise _bad(item, kind)
        _move(item, "VERIFYING", None, at)
    elif kind == "VERIFIED_SUCCESS":
        if item.state not in AFTER_SUBMIT:
            raise _bad(item, kind)
        evidence = event.get("evidence") or {}
        if evidence.get("method") not in EVIDENCE_METHODS or not str(evidence.get("value") or "").strip():
            raise ApiError(422, "EVIDENCE_REQUIRED", "ต้องมีหลักฐานผลโพสต์ที่ผูกกับบัญชีและคลิป (PRD §H)")
        item.evidence = {"method": evidence["method"], "value": str(evidence["value"])[:300],
                         "account": str(evidence.get("account") or "")[:64] or None}
        item.verified_at = at
        _release(item)
        _move(item, "VERIFIED_SUCCESS", None, at)
    elif kind == "UNKNOWN":
        if item.state not in AFTER_SUBMIT:
            raise _bad(item, kind)
        _release(item)
        _move(item, "UNKNOWN", str(event.get("code") or "UNVERIFIED")[:40], at)
    elif kind in ("RETRYABLE_FAILED", "NEEDS_ACTION"):
        if item.state not in BEFORE_SUBMIT:
            # After Submit a failure is not knowable from the Agent alone: it must be UNKNOWN.
            raise _bad(item, kind)
        _release(item)
        code = str(event.get("code") or kind)[:40]
        if kind == "RETRYABLE_FAILED" and item.attempts < MAX_ATTEMPTS:
            _move(item, "SCHEDULED", code, at)  # same slot; the late-post rules still apply
        else:
            _move(item, "NEEDS_ACTION", code, at)
    else:
        raise ApiError(422, "UNKNOWN_EVENT", "ไม่รู้จักชนิด event", {"type": kind})

    db.add(ScheduleItemEvent(workspace_id=item.workspace_id, item_id=item.id, event_id=event_id, type=kind,
                             detail=(str(event.get("detail") or "")[:300] or None)))
    if item.state in IN_FLIGHT:
        item.lease_expires_at = at + timedelta(seconds=LEASE_S)
    if item.state in FINAL:
        _maybe_complete(db, item.series_id, at)
    return item, False, refusal
