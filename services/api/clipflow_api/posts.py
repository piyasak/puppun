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
Only the lease holder may report; ids are deduplicated. Each post carries the mode it was handed
out with (Q-42): live only under an admin's posting grant for the phone's account (posting_grants)
and only to an Agent that says it can post live; otherwise a dry run. SUBMITTING is refused for a
dry run; for a live post it re-checks approval (§G.6 "again before submission") and then counts one
grant use under the grant's row lock. Success needs evidence (§H). The test-only "live" server mode
(app.create_app) makes every post live without a grant, to drive the state machine with simulated Agents.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from . import devices as device_rules
from . import notify, posting_grants, schedules, slots
from .agent_sessions import AgentContext
from .errors import ApiError
from .models import (
    Clip,
    ClipMetadata,
    Device,
    Environment,
    PostingGrant,
    ScheduleItem,
    ScheduleItemEvent,
    ScheduleSeries,
)

LEASE_S = 300
# Verifying sends no event until it ends: a public post's check opens several videos and retries with waits
# (tx1, 2026-10-16: fb8f276c verified after > 5 min and the lease had already turned it UNKNOWN).
VERIFY_LEASE_S = 1200
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
        notify.on_post_event(db, item)  # Q-52: a person is needed (never raises)


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


def _running(db: Session, environment_id: uuid.UUID) -> int:
    """Posts between a claim and their result on this Environment's phones."""
    return db.scalar(select(func.count()).select_from(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id)
                     .where(Device.environment_id == environment_id, ScheduleItem.state.in_(IN_FLIGHT))) or 0


def _busy(db: Session, device_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists().where(ScheduleItem.device_id == device_id,
                                                ScheduleItem.state.in_(BUSY)))))


def claim(db: Session, ctx: AgentContext, ready_serials: list[str], *, can_post_live: bool = False,
          can_skip_account_check: bool = False, can_post_public: bool = False,
          server_mode: str = "dry_run") -> ScheduleItem | None:
    at = now()
    expire_leases(db, ctx.environment_id, at)
    apply_offline_policy(db, ctx.environment_id, at)
    # Q-54: no more posts running at once on this Environment than its cap (the owner's setting, else its
    # phones). The row lock makes two claims at the same moment count one after the other.
    env = db.scalars(select(Environment).where(Environment.id == ctx.environment_id).with_for_update()).first()
    if env is not None and _running(db, env.id) >= (env.max_parallel_posts or max(env.device_limit, 1)):
        return None
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
    ).order_by(ScheduleItem.scheduled_at, ScheduleItem.created_at, ScheduleItem.seq).limit(50)  # ties: first scheduled first
        .with_for_update(of=ScheduleItem, skip_locked=True)).all()
    tried: set[uuid.UUID] = set()
    for item in due:
        if item.device_id in tried:
            continue  # one post per phone per claim; the next waits for this one (Q-05)
        phone = db.scalars(select(Device).where(Device.id == item.device_id)
                           .with_for_update(skip_locked=True)).first()
        if phone is None or _busy(db, phone.id):
            tried.add(item.device_id)
            continue
        reason = schedules.dispatchable(db, item)
        if reason in ("SERIES_NOT_ACTIVE", "SUBSCRIPTION_INACTIVE"):
            # Paused or not paid: this one waits, keeping its slot rules, but it does not hold the phone. Staging,
            # 2026-10-12/13: a paused series' overdue post came first on every claim and blocked the phone's
            # other posts (another series and a "post now") for 16 hours.
            continue
        tried.add(item.device_id)
        if reason:
            _move(item, "NEEDS_ACTION", reason, at)
            continue
        item.posting_mode, item.grant_id, item.grant_used = "dry_run", None, False
        if server_mode == "live":
            item.posting_mode = "live"  # test-only server mode
        elif can_post_live:
            # Q-48: with the Workspace's account check off, an Agent that can post without it uses any grant.
            any_account = can_skip_account_check and not posting_grants.account_check(db, item.workspace_id)
            grant = posting_grants.for_claim(db, item.workspace_id, phone.expected_account, at, any_account=any_account,
                                             public_ok=can_post_public)
            if grant is not None:
                item.posting_mode, item.grant_id = "live", grant.id
        item.attempts += 1
        item.lease_session_id, item.lease_expires_at = ctx.session_id, at + timedelta(seconds=LEASE_S)
        item.claimed_at = item.claimed_at or at
        _move(item, "CLAIMED", None, at)
        return item
    return None


def agent_state(db: Session, ctx: AgentContext, item_id: uuid.UUID) -> dict:
    item = db.scalars(select(ScheduleItem).join(Device, Device.id == ScheduleItem.device_id).where(
        ScheduleItem.id == item_id, Device.environment_id == ctx.environment_id)).first()
    if item is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบรายการนี้")
    return {"id": str(item.id), "state": item.state, "reason": item.reason, "attempt": item.attempts}


def spec(db: Session, item: ScheduleItem, storage, ttl_s: int, posting_mode: str) -> dict:
    """What the Agent needs for one post: the bound file and text, the phone and account."""
    clip = db.get(Clip, item.clip_id)
    meta = db.scalars(select(ClipMetadata).where(ClipMetadata.clip_id == clip.id,
                                                 ClipMetadata.version == item.metadata_version)).one()
    phone = db.get(Device, item.device_id)
    grant = db.get(PostingGrant, item.grant_id) if item.grant_id else None
    return {
        "id": str(item.id), "state": item.state, "state_version": item.state_version, "attempt": item.attempts,
        "posting_mode": item.posting_mode or posting_mode, "scheduled_at": item.scheduled_at.isoformat(),
        "grant": {"id": str(grant.id), "visibility": grant.visibility} if grant else None,
        "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None,
        "device": {"serial": phone.serial, "expected_account": phone.expected_account,
                   # Q-48: False = the Agent neither checks the account nor ties the evidence to it.
                   "account_check": posting_grants.account_check(db, item.workspace_id)},
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
    mode = item.posting_mode or posting_mode  # items handed out before 0018 follow the server mode
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
        if item.state != "PREPARING" or mode != "dry_run":
            raise _bad(item, kind)
        _release(item)
        _move(item, "DRY_RUN_DONE", "STOPPED_BEFORE_SUBMIT", at)
    elif kind == "SUBMITTING":
        if item.state != "PREPARING":
            raise _bad(item, kind)
        if mode != "live" or (item.grant_id is None and posting_mode != "live"):
            raise ApiError(409, "POSTING_DISABLED", "โพสต์นี้ไม่ได้รับอนุญาตให้โพสต์จริง (dry-run) หยุดก่อนกดโพสต์")
        reason = schedules.dispatchable(db, item, expected_state="PREPARING")
        if not reason and item.grant_id is not None:
            reason = posting_grants.use(db, item, db.get(Device, item.device_id).expected_account, at)
        if reason and reason.startswith("POSTING_GRANT"):
            _release(item)
            _move(item, "NEEDS_ACTION", reason, at)
            event["detail"] = f"refused: {reason}"
            refusal = ApiError(409, "POSTING_NOT_ALLOWED", "สิทธิ์โพสต์จริงของบัญชีนี้หมดหรือถูกยกเลิก ห้ามกดโพสต์",
                               {"reason": reason})
        elif reason:
            _release(item)
            # An expired subscription only makes the post wait, as it would before a claim (T22).
            _move(item, "SCHEDULED" if reason == "SUBSCRIPTION_INACTIVE" else "NEEDS_ACTION", reason, at)
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
        item.lease_expires_at = at + timedelta(seconds=VERIFY_LEASE_S if item.state == "VERIFYING" else LEASE_S)
    if item.state in FINAL:
        _maybe_complete(db, item.series_id, at)
    return item, False, refusal


# --- reconciliation (P5.5, PRD §H) ----------------------------------------------------------------

RESOLUTIONS = ("found_published", "confirmed_not_published", "still_unknown")
# NEEDS_ACTION reasons a person may simply retry once fixed. Approval/text/phone problems are not
# here: they are fixed by approving again (rebinds automatically) or by scheduling elsewhere.
RETRYABLE_REASONS = ("AGENT_LOST", "ACCOUNT_MISMATCH", "ACCOUNT_UNREADABLE", "TRANSFER_FAILED", "GALLERY_NOT_FOUND", "FILE_UNAVAILABLE",
                     "DOWNLOAD_FAILED", "FILE_HASH_MISMATCH", "DEVICE_NOT_CONNECTED", "AGENT_ERROR", "WIFI_OFFLINE",
                     "THAI_KEYBOARD_MISSING", "UNKNOWN_SCREEN", "SCREEN_CHANGED", "KEYBOARD_SHOWN",
                     "CAPTION_MISMATCH", "VISIBILITY_NOT_SET")


def _next_slot(db: Session, item: ScheduleItem, at: datetime) -> datetime:
    series = db.get(ScheduleSeries, item.series_id)
    return slots.normalize(at, slots.Window(series.window_start_min, series.window_end_min), slots.zone(series.timezone))


def resolve(db: Session, item: ScheduleItem, *, decision: str, evidence: str, actor: uuid.UUID,
            expected_state_version: int) -> None:
    """A person settles an UNKNOWN post with evidence. Nothing is preselected and nothing is retried
    without a confirmed "not published"."""
    if item.state != "UNKNOWN":
        raise ApiError(409, "NOT_UNKNOWN", "ยืนยันผลได้เฉพาะโพสต์ที่ไม่ทราบผล", {"state": item.state})
    if item.state_version != expected_state_version:
        raise ApiError(409, "VERSION_CONFLICT", "รายการถูกเปลี่ยนไปแล้ว โหลดใหม่", {"current_version": item.state_version})
    if decision not in RESOLUTIONS:
        raise ApiError(422, "VALIDATION_ERROR", "ต้องเลือกผลที่ตรวจพบ")
    note = evidence.strip()
    if len(note) < 5:
        raise ApiError(422, "EVIDENCE_REQUIRED", "ต้องระบุหลักฐาน เช่น ลิงก์โพสต์ หรือสิ่งที่ตรวจในแอป TikTok")
    at = now()
    record = {"method": "manual_resolution", "decision": decision, "value": note[:300], "resolved_by": str(actor),
              "at": at.isoformat()}
    if decision == "found_published":
        item.evidence, item.verified_at = record, at
        _move(item, "VERIFIED_SUCCESS", "RESOLVED_PUBLISHED", at)
        _maybe_complete(db, item.series_id, at)
    elif decision == "confirmed_not_published":
        item.evidence = record
        item.scheduled_at = max(item.scheduled_at, _next_slot(db, item, at))  # once, at the next allowed time
        item.submitted_at = None
        _move(item, "SCHEDULED", "RESOLVED_NOT_PUBLISHED", at)
    else:
        item.evidence = record  # stays UNKNOWN; the phone stays paused (PRD §H)
        item.state_version += 1
        item.updated_at = at
    db.add(ScheduleItemEvent(workspace_id=item.workspace_id, item_id=item.id, event_id=uuid.uuid4().hex,
                             type="RESOLVE", detail=f"{decision}: {note}"[:300]))


def retry(db: Session, item: ScheduleItem, expected_state_version: int) -> None:
    if item.state != "NEEDS_ACTION" or item.reason not in RETRYABLE_REASONS:
        raise ApiError(409, "NOT_RETRYABLE", "รายการนี้ลองใหม่โดยตรงไม่ได้", {"state": item.state, "reason": item.reason})
    if item.state_version != expected_state_version:
        raise ApiError(409, "VERSION_CONFLICT", "รายการถูกเปลี่ยนไปแล้ว โหลดใหม่", {"current_version": item.state_version})
    at = now()
    reason = schedules.dispatchable(db, item, expected_state="NEEDS_ACTION")
    if reason:
        raise ApiError(409, "NOT_DISPATCHABLE", "คลิปหรือโทรศัพท์ยังไม่พร้อม", {"reason": reason})
    item.scheduled_at = max(item.scheduled_at, _next_slot(db, item, at))
    item.attempts = 0
    _move(item, "SCHEDULED", "RETRY_REQUESTED", at)
