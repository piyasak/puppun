"""Job lifecycle on the server (FR-02..FR-05, FR-21, G3-04). The Agent does the media work (Q-15).

Agent protocol:
- `claim` leases the oldest claimable job of the session's Environment (SKIP LOCKED, so two
  Agents never get the same job). A lease lasts LEASE_S and is renewed by every event.
- Events carry an Agent-generated `event_id`; a repeated id returns the current state and
  changes nothing. Only the session holding the lease may report; a stale Agent gets
  LEASE_LOST and must stop. Terminal jobs answer JOB_NOT_ACTIVE.
- A job whose lease expired (Agent lost) is claimable again; after MAX_ATTEMPTS it fails and
  its quota is released.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import billing, clips, quota
from .agent_sessions import AgentContext
from .entitlements import entitlement
from .errors import ApiError
from .models import Clip, Environment, Job, JobEvent, RightsAcceptance, ScheduleItem
from .sources import check_file_label, check_folder_label, classify_url

LEASE_S = 300
MAX_ATTEMPTS = 3
ACTIVE = ("SOURCE_VALIDATED", "DOWNLOADING", "ANALYZING", "RENDERING")
TERMINAL = ("READY_FOR_REVIEW", "FAILED", "NEEDS_ACTION", "CANCELLED")
STAGE_ORDER = {"SOURCE_VALIDATED": 0, "DOWNLOADING": 1, "ANALYZING": 2, "RENDERING": 3}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def now() -> datetime:
    return datetime.now(UTC)


# --- web side -------------------------------------------------------------------------------

AUTO_MAX_CLIPS = 100  # Q-32: cap for a whole-source split (a 2-hour source at 1 min per clip fits)
LAST_CLIP_STRETCH = 1.2  # the last clip of a whole-source split may run this much over clip_max_s
PRECUT_MAX_S = 600  # a clip already cut (local_clips) may be up to TikTok's 10 minutes, and as short as 1 s


def longest_clip_s(job: Job, index: int) -> float:
    """Upper length limit of clip `index`: the last clip of a whole-source split may stretch (Q-32)."""
    return job.clip_max_s * (LAST_CLIP_STRETCH if job.auto_clips and index == job.planned_clips else 1)


def create(db: Session, *, workspace_id, user_id, environment_id, idempotency_key: str, source: dict,
           requested_clips: int, clip_min_s: int, clip_max_s: int, subtitles: bool, review_mode: str,
           auto_clips: bool = False, delete_after_post: bool = False, caption_title: str | None = None,
           caption_hashtags: list[str] | None = None) -> tuple[Job, bool]:
    """Create a job, or return the existing one for a repeated idempotency key. Returns (job, created)."""
    existing = db.scalars(select(Job).where(Job.workspace_id == workspace_id,
                                            Job.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing, False

    env = db.scalars(select(Environment).where(Environment.id == environment_id,
                                               Environment.workspace_id == workspace_id)).first()
    if env is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบ Environment นี้")
    rights = db.scalars(select(RightsAcceptance).where(RightsAcceptance.workspace_id == workspace_id)
                        .order_by(RightsAcceptance.accepted_at.desc())).first()
    if rights is None:
        raise ApiError(403, "RIGHTS_REQUIRED", "ต้องยอมรับคำรับรองสิทธิ์ในเนื้อหาก่อน")

    if source.get("kind") == "url":
        kind, url, label = classify_url(source.get("url") or ""), source["url"].strip(), None
    elif source.get("kind") == "local_file":
        kind, url, label = "local_file", None, check_file_label(source.get("file_name") or "")
    elif source.get("kind") == "local_clips":
        # Clips already cut, one folder per series in EP order (PO 2026-10-11): nothing is cut or rendered,
        # every file in the folder becomes one clip (up to AUTO_MAX_CLIPS), so no subtitles and no length plan.
        kind, url, label = "local_clips", None, check_folder_label(source.get("folder") or "")
        requested_clips, auto_clips, subtitles, delete_after_post = AUTO_MAX_CLIPS, True, False, False
        clip_min_s, clip_max_s = 15, PRECUT_MAX_S
    else:
        raise ApiError(422, "VALIDATION_ERROR", "ต้องระบุแหล่งที่มาเป็นลิงก์หรือไฟล์บนเครื่อง Agent")
    from .clips import normalize_hashtags  # clips imports this module

    caption_title = " ".join((caption_title or "").split())[:100] or None
    caption_hashtags = normalize_hashtags(caption_hashtags) if caption_hashtags else None

    billing.require_active(entitlement(db, workspace_id).cycle)  # an expired subscription makes no new jobs
    # Early, friendly check; the binding reservation happens when the clip count is known (E-04).
    clips = quota.summary(db, workspace_id, now())
    if not clips["unlimited"] and clips["available"] <= 0:
        raise ApiError(409, "QUOTA_EXHAUSTED", "โควตาคลิปของเดือนนี้หมดแล้ว")

    job = Job(
        workspace_id=workspace_id, environment_id=env.id, created_by=user_id, idempotency_key=idempotency_key,
        source_kind=kind, source_url=url, source_label=label, rights_acceptance_id=rights.id,
        requested_clips=requested_clips, auto_clips=auto_clips, delete_after_post=delete_after_post,
        clip_min_s=clip_min_s, clip_max_s=clip_max_s,
        subtitles=subtitles,
        review_mode=review_mode, seed=secrets.randbelow(2**31), state="RECEIVED", state_version=1, attempts=0,
        caption_title=caption_title, caption_hashtags=caption_hashtags,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:  # the same key arrived twice at the same moment
        db.rollback()
        return db.scalars(select(Job).where(Job.workspace_id == workspace_id,
                                            Job.idempotency_key == idempotency_key)).one(), False
    return job, True


def _finish(db: Session, job: Job, state: str, *, code: str | None = None, detail: str | None = None,
            reason: str) -> None:
    quota.release_outstanding(db, job.workspace_id, job.id, job.quota_period, reason)
    job.state, job.error_code, job.error_detail = state, code, (detail or "")[:500] or None
    job.lease_session_id, job.lease_expires_at = None, None
    job.finished_at = job.updated_at = now()
    job.state_version += 1


MAX_RESETS = 10


def remake_indexes(db: Session, job: Job) -> list[int]:
    """Delivered clips kept on an Agent's PC that may still be posted: not deleted after posting and
    not already posted (a posted clip needs no file)."""
    posted = select(ScheduleItem.clip_id).where(ScheduleItem.state == "VERIFIED_SUCCESS")
    rows = db.scalars(select(Clip.clip_index).where(
        Clip.job_id == job.id, Clip.uploaded_at.is_not(None), Clip.file_location == "agent",
        Clip.agent_file_deleted_at.is_(None), Clip.id.not_in(posted)).order_by(Clip.clip_index)).all()
    return list(rows)


def reset(db: Session, job: Job) -> str:
    """Start a job again (PO 2026-10-10). Returns "remake" or "restart".

    - remake: clips were delivered and their files stay on an Agent's PC (Q-33). The Agent makes the
      missing files again from the same source with the same seed (same selection; usually the same
      file and hash) or finds them where they were moved. Nothing is charged again (quota is settled
      once per clip). Posts parked because the file was missing go back to their schedule when done.
    - restart: nothing was delivered (e.g. the source file was not found). The job starts over from
      the source; quota is reserved again when the Agent validates it (it was released on failure).
    """
    if job.state not in TERMINAL or job.state == "CANCELLED":
        raise ApiError(409, "JOB_NOT_RESETTABLE", "เริ่มงานใหม่ได้เฉพาะงานที่จบแล้วหรือล้มเหลว (ยกเลิกแล้วเริ่มใหม่ไม่ได้)",
                       {"state": job.state})
    if job.reset_count >= MAX_RESETS:
        raise ApiError(409, "TOO_MANY_RESETS", "เริ่มงานนี้ใหม่หลายครั้งแล้ว สร้างงานใหม่แทน")
    at = now()
    delivered = db.scalar(select(func.count()).select_from(Clip).where(Clip.job_id == job.id,
                                                                        Clip.uploaded_at.is_not(None)))
    if delivered:
        if not remake_indexes(db, job):
            raise ApiError(409, "NOTHING_TO_REMAKE", "ไม่มีคลิปที่ต้องทำไฟล์ใหม่ (โพสต์แล้วหรือลบไฟล์แล้วทั้งหมด)")
        job.state, mode = "SOURCE_VALIDATED", "remake"
        job.remake_requested_at = at
    else:
        db.execute(delete(Clip).where(Clip.job_id == job.id))  # reported but never delivered
        job.state, mode = "RECEIVED", "restart"
        job.planned_clips, job.quota_period, job.source_duration_s, job.notice = None, None, None, None
    job.error_code = job.error_detail = None
    job.lease_session_id, job.lease_expires_at = None, None
    job.attempts, job.finished_at, job.updated_at = 0, None, at
    job.reset_count += 1
    job.state_version += 1
    return mode


def cancel(db: Session, job: Job) -> None:
    """Phase-aware: unfinished work stops and held quota returns; delivered clips stay."""
    if job.state in TERMINAL:
        raise ApiError(409, "JOB_NOT_ACTIVE", "งานนี้จบแล้ว ยกเลิกไม่ได้", {"state": job.state})
    _finish(db, job, "CANCELLED", reason="job_cancelled")


# --- Agent side -----------------------------------------------------------------------------

def _claimable(ctx: AgentContext, at: datetime, kinds: list[str] | None):
    # Unfinished and not leased to a live Agent. A claimed job can still be RECEIVED (the Agent
    # has not validated the source yet), so the lease decides, not the state (bug found 2026-10-08).
    stmt = select(Job).where(
        Job.environment_id == ctx.environment_id,
        Job.state.in_(("RECEIVED", *ACTIVE)),
        or_(Job.lease_expires_at.is_(None), Job.lease_expires_at < at),
    )
    if not kinds or "local_clips" not in kinds:
        stmt = stmt.where(Job.source_kind != "local_clips")  # Agents before 0.5.0 cannot read a clips folder
    return stmt.order_by(Job.created_at).with_for_update(skip_locked=True)


def claim(db: Session, ctx: AgentContext, kinds: list[str] | None = None) -> Job | None:
    """`kinds`: the source kinds this Agent can work on (sent from 0.5.0); None = an older Agent."""
    at = now()
    while True:
        job = db.scalars(_claimable(ctx, at, kinds).limit(1)).first()
        if job is None:
            return None
        if job.attempts >= MAX_ATTEMPTS:
            _finish(db, job, "FAILED", code="AGENT_LOST", detail="Agent หยุดทำงานระหว่างผลิตคลิปหลายครั้ง",
                    reason="agent_lost")
            continue
        job.attempts += 1
        job.lease_session_id, job.lease_expires_at = ctx.session_id, at + timedelta(seconds=LEASE_S)
        job.state_version += 1
        job.updated_at = at
        return job


def _locked_job(db: Session, ctx: AgentContext, job_id: uuid.UUID) -> Job:
    job = db.scalars(select(Job).where(Job.id == job_id, Job.environment_id == ctx.environment_id)
                     .with_for_update()).first()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบงานนี้")
    return job


def lease_holder_job(db: Session, ctx: AgentContext, job_id: uuid.UUID) -> Job:
    """Locked job for a clip upload: still rendering and leased to this session."""
    job = _locked_job(db, ctx, job_id)
    if job.state in TERMINAL:
        raise ApiError(409, "JOB_NOT_ACTIVE", "งานนี้จบแล้วหรือถูกยกเลิก หยุดทำงานนี้", {"state": job.state})
    if job.lease_session_id != ctx.session_id or job.lease_expires_at is None or job.lease_expires_at <= now():
        raise ApiError(409, "LEASE_LOST", "งานนี้ไม่ได้อยู่กับ Agent นี้แล้ว หยุดทำงานนี้")
    if job.state != "RENDERING":
        raise ApiError(409, "BAD_EVENT_ORDER", "อัปโหลดคลิปได้เฉพาะระหว่าง RENDERING", {"state": job.state})
    job.lease_expires_at = now() + timedelta(seconds=LEASE_S)  # an upload counts as activity
    return job


def apply_event(db: Session, ctx: AgentContext, job_id: uuid.UUID, event: dict) -> tuple[Job, bool]:
    """Apply one Agent event. Returns (job, duplicate)."""
    job = _locked_job(db, ctx, job_id)
    event_id, kind = event["event_id"], event["type"]
    if db.scalars(select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.event_id == event_id)).first():
        return job, True
    if job.state in TERMINAL:
        raise ApiError(409, "JOB_NOT_ACTIVE", "งานนี้จบแล้วหรือถูกยกเลิก หยุดทำงานนี้", {"state": job.state})
    at = now()
    if job.lease_session_id != ctx.session_id or job.lease_expires_at is None or job.lease_expires_at <= at:
        raise ApiError(409, "LEASE_LOST", "งานนี้ไม่ได้อยู่กับ Agent นี้แล้ว หยุดทำงานนี้")

    handler = HANDLERS.get(kind)
    if handler is None:
        raise ApiError(422, "UNKNOWN_EVENT", "ไม่รู้จักชนิด event", {"type": kind})
    handler(db, job, event, at)
    if kind == "clip_rendered":  # the file stays on this installation's PC (Q-33): only it can delete it
        db.execute(update(Clip).where(Clip.job_id == job.id, Clip.clip_index == int(event["index"]))
                   .values(agent_installation_id=ctx.installation_ref))
    db.add(JobEvent(workspace_id=job.workspace_id, job_id=job.id, event_id=event_id, type=kind))
    if job.state not in TERMINAL:
        job.lease_expires_at = at + timedelta(seconds=LEASE_S)
    job.updated_at = at
    return job, False


def _bad_order(job: Job, kind: str) -> ApiError:
    return ApiError(409, "BAD_EVENT_ORDER", "event นี้มาผิดลำดับ", {"state": job.state, "type": kind})


def _source_validated(db: Session, job: Job, e: dict, at: datetime) -> None:
    if job.state != "RECEIVED":
        raise _bad_order(job, e["type"])
    duration, possible = int(e["duration_s"]), int(e["possible_clips"])
    if duration <= 0 or possible < 0:
        raise ApiError(422, "VALIDATION_ERROR", "duration_s/possible_clips ไม่ถูกต้อง")
    job.source_duration_s = duration
    if possible == 0:  # T09: never pad with repeats; nothing reserved, nothing charged
        job.planned_clips = 0
        _finish(db, job, "FAILED", code="INSUFFICIENT_SOURCE",
                detail=f"ต้นฉบับยาว {duration} วินาที ตัดคลิป {job.clip_min_s}–{job.clip_max_s} วินาทีไม่ได้",
                reason="insufficient_source")
        return
    planned = min(job.requested_clips, possible)
    # Whole-source split (Q-32): the source decides; if it needs more than the quota left, the job
    # stops for the user (QUOTA_EXCEEDED below) instead of quietly making only part of it.
    try:
        job.quota_period = quota.reserve(db, job.workspace_id, job.id, planned, at)
    except quota.QuotaExceeded as exc:
        job.planned_clips = planned
        _finish(db, job, "NEEDS_ACTION", code="QUOTA_EXCEEDED",
                detail=f"ต้องใช้ {planned} คลิป แต่โควตาเหลือ {exc.available}", reason="quota_exceeded")
        return
    job.planned_clips = planned
    job.notice = "INSUFFICIENT_SOURCE" if planned < job.requested_clips and not job.auto_clips else None
    job.state = "SOURCE_VALIDATED"
    job.state_version += 1


def _stage(db: Session, job: Job, e: dict, at: datetime) -> None:
    target = e.get("stage")
    if target not in ("DOWNLOADING", "ANALYZING", "RENDERING") or job.state not in STAGE_ORDER:
        raise _bad_order(job, e["type"])
    if STAGE_ORDER[target] < STAGE_ORDER[job.state]:
        raise _bad_order(job, e["type"])
    if target != job.state:
        job.state = target
        job.state_version += 1


def episode_caption(title: str, index: int, total: int | None) -> str:
    return f"{title} — ตอนที่ {index}/{total}" if total else f"{title} — ตอนที่ {index}"


def _clip_rendered(db: Session, job: Job, e: dict, at: datetime) -> None:
    if job.state != "RENDERING":
        raise _bad_order(job, e["type"])
    index = int(e["index"])
    if not 1 <= index <= (job.planned_clips or 0):
        raise ApiError(422, "VALIDATION_ERROR", "ลำดับคลิปเกินจำนวนที่วางแผนไว้")
    sha = str(e["sha256"]).lower()
    duration_ms = int(e["duration_ms"])
    if not SHA256_RE.match(sha):
        raise ApiError(422, "VALIDATION_ERROR", "sha256 ไม่ถูกต้อง")
    shortest_ms, longest_ms = ((1000, PRECUT_MAX_S * 1000) if job.source_kind == "local_clips"
                               else (job.clip_min_s * 1000 - 1000, longest_clip_s(job, index) * 1000 + 1000))
    if not shortest_ms <= duration_ms <= longest_ms:
        raise ApiError(422, "CLIP_DURATION_OUT_OF_RANGE", "ความยาวคลิปไม่อยู่ในช่วงที่กำหนด")
    checks, agent_path = clips.reported_checks(e.get("checks")), clips.reported_path(e.get("local_path"))
    existing = db.scalars(select(Clip).where(Clip.job_id == job.id, Clip.clip_index == index)
                          .with_for_update()).first()
    if existing is not None:
        if existing.render_sha256 == sha:
            if existing.uploaded_at is None and checks is not None:
                existing.check_results, existing.agent_path = checks, agent_path
            return
        if existing.uploaded_at is not None and job.remake_requested_at is None:  # delivered files are never swapped
            raise ApiError(409, "CLIP_CONFLICT", "คลิปลำดับนี้ถูกรายงานแล้วด้วยไฟล์อื่น")
        if existing.uploaded_at is not None:
            # Remake (PO 2026-10-10) gave a different file: it must be delivered and approved again; scheduled
            # posts bound to the old hash are parked by the approval rules (FILE_CHANGED), never posted blindly.
            existing.uploaded_at = existing.preview_key = None
            existing.approved_sha256 = existing.approved_metadata_version = existing.approved_at = None
            existing.approval_mode = existing.approved_by = None
        # Reported but never delivered: an Agent that restarted mid-job rendered it again (E-37).
        existing.start_ms, existing.end_ms, existing.duration_ms = int(e["start_ms"]), int(e["end_ms"]), duration_ms
        existing.render_sha256, existing.size_bytes = sha, int(e["size_bytes"])
        existing.template_version = str(e["template_version"])[:40]
        existing.title = (e.get("title") or "")[:200] or None
        existing.check_results, existing.agent_path = checks, agent_path
        return
    clip = Clip(
        workspace_id=job.workspace_id, job_id=job.id, clip_index=index, start_ms=int(e["start_ms"]),
        end_ms=int(e["end_ms"]), seed=job.seed, template_version=str(e["template_version"])[:40],
        render_sha256=sha, size_bytes=int(e["size_bytes"]), duration_ms=duration_ms,
        title=(e.get("title") or "")[:200] or None, metadata_version=1,
        check_results=checks, agent_path=agent_path,  # Q-33: checks made on the Agent, delivered with its still
    )
    db.add(clip)
    db.flush()
    caption, hashtags = e.get("caption"), e.get("hashtags")
    if job.caption_title:  # the text set when the job was made wins over the Agent's default
        caption = episode_caption(job.caption_title, index, job.planned_clips)
    if job.caption_hashtags is not None:
        hashtags = job.caption_hashtags
    db.add(clips.first_metadata(clip, caption, hashtags))
    # Quota is settled when the file arrives and matches this hash (clips.accept_upload).


def _completed(db: Session, job: Job, e: dict, at: datetime) -> None:
    if job.state != "RENDERING":
        raise _bad_order(job, e["type"])
    reported = db.scalars(select(Clip).where(Clip.job_id == job.id)).all()
    waiting = [c.clip_index for c in reported if c.uploaded_at is None]
    if waiting:
        raise ApiError(409, "CLIPS_NOT_UPLOADED", "ยังอัปโหลดคลิปไม่ครบ", {"clip_indexes": waiting})
    delivered = reported
    if not delivered:
        _finish(db, job, "FAILED", code="RENDER_FAILED", detail="ไม่มีคลิปที่ผลิตสำเร็จ", reason="render_failed")
        return
    if len(delivered) < (job.planned_clips or 0):
        job.notice = "PARTIAL_RENDER"
    if job.remake_requested_at is not None:
        _after_remake(db, job, at)
    _finish(db, job, "READY_FOR_REVIEW", reason="job_completed_short")


def _after_remake(db: Session, job: Job, at: datetime) -> None:
    """The files are back: posts parked as FILE_UNAVAILABLE return to their schedule (next allowed time)."""
    from . import posts, schedules

    job.remake_requested_at = None
    items = db.scalars(select(ScheduleItem).join(Clip, Clip.id == ScheduleItem.clip_id).where(
        Clip.job_id == job.id, ScheduleItem.state == "NEEDS_ACTION", ScheduleItem.reason == "FILE_UNAVAILABLE")
        .with_for_update(of=ScheduleItem)).all()
    for item in items:
        if schedules.dispatchable(db, item, expected_state="NEEDS_ACTION") is None:
            posts.retry(db, item, item.state_version)
    for clip in db.scalars(select(Clip).where(Clip.job_id == job.id)).all():
        schedules.sync_clip_items(db, clip)  # a remade clip with a new file parks its posts until approved


def _failed(db: Session, job: Job, e: dict, at: datetime) -> None:
    code = str(e.get("code") or "AGENT_ERROR")[:40]
    job.remake_requested_at = None  # a failed remake leaves the delivered clips as they were
    delivered = db.scalars(select(Clip.id).where(Clip.job_id == job.id, Clip.uploaded_at.is_not(None))).first()
    if delivered is not None:  # keep what was delivered (uploaded); the rest is released
        job.notice = "PARTIAL_RENDER"
        _finish(db, job, "READY_FOR_REVIEW", code=code, detail=e.get("detail"), reason="job_failed_partial")
    else:
        _finish(db, job, "FAILED", code=code, detail=e.get("detail"), reason="job_failed")


def _progress(db: Session, job: Job, e: dict, at: datetime) -> None:
    """Keep-alive while a long step runs (analysis, download, render): renews the lease only."""


HANDLERS = {
    "progress": _progress,
    "source_validated": _source_validated,
    "stage": _stage,
    "clip_rendered": _clip_rendered,
    "completed": _completed,
    "failed": _failed,
}
