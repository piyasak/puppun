"""Clip delivery, metadata versions and approval (P3.2, FR-06..FR-08, G3-03/G3-05).

- Delivery: the Agent uploads the rendered file; the server hashes it itself and accepts it only
  if it matches the `render_sha256` reported in `clip_rendered`. Quota is settled here, when a
  clip is actually delivered, not when it is merely announced.
- Checks: ffprobe on the server (`mediacheck`); results are stored on the clip.
- Metadata: caption + hashtags, one row per version. The title is burned into the video, so it
  is not editable here (a change needs a re-render, PRD §F).
- Approval names a metadata version and a file hash. Editing the caption makes a new version,
  so the old approval no longer applies. Review mode needs a person; auto mode approves only
  clips whose checks passed (FR-08). Nothing unapproved may be scheduled (P4 reads `approved`).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mediacheck, quota
from .errors import ApiError
from .models import Clip, ClipMetadata, Job

HASHTAG_RE = re.compile(r"^#?[0-9A-Za-z_฀-๿]{1,50}$")
MAX_HASHTAGS = 30


def now() -> datetime:
    return datetime.now(UTC)


def normalize_hashtags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_HASHTAGS:
        raise ApiError(422, "VALIDATION_ERROR", f"แฮชแท็กได้ไม่เกิน {MAX_HASHTAGS} อัน")
    out = []
    for tag in tags:
        tag = tag.strip()
        if not HASHTAG_RE.match(tag):
            raise ApiError(422, "VALIDATION_ERROR", "แฮชแท็กใช้ได้เฉพาะตัวอักษร ตัวเลข และ _", {"tag": tag[:60]})
        tag = "#" + tag.lstrip("#")
        if tag.lower() not in (t.lower() for t in out):
            out.append(tag)
    return out


def is_approved(clip: Clip) -> bool:
    return (clip.approved_metadata_version is not None
            and clip.approved_metadata_version == clip.metadata_version
            and clip.approved_sha256 == clip.render_sha256)


def current_metadata(db: Session, clip: Clip) -> ClipMetadata:
    return db.scalars(select(ClipMetadata).where(ClipMetadata.clip_id == clip.id,
                                                 ClipMetadata.version == clip.metadata_version)).one()


def first_metadata(clip: Clip, caption: str | None, hashtags: list[str] | None) -> ClipMetadata:
    return ClipMetadata(workspace_id=clip.workspace_id, clip_id=clip.id, version=1,
                        caption=(caption or clip.title or "")[:2200], hashtags=normalize_hashtags(hashtags or []))


def _auto_approve(clip: Clip) -> None:
    clip.approved_metadata_version, clip.approved_sha256 = clip.metadata_version, clip.render_sha256
    clip.approved_at, clip.approved_by, clip.approval_mode = now(), None, "auto"


def accept_upload(db: Session, storage, job: Job, clip: Clip, temp: Path, size: int, digest: str) -> None:
    """Called with the job row locked, after the body was streamed to `temp` and hashed."""
    if digest != clip.render_sha256:
        raise ApiError(422, "HASH_MISMATCH", "ไฟล์ที่อัปโหลดไม่ตรงกับ sha256 ที่รายงานไว้",
                       {"expected": clip.render_sha256, "received": digest})
    if size != clip.size_bytes:
        raise ApiError(422, "SIZE_MISMATCH", "ขนาดไฟล์ไม่ตรงกับที่รายงานไว้")
    if clip.uploaded_at is not None:  # same file again: nothing to do
        return
    key = f"{clip.workspace_id}/{job.id}/clip_{clip.clip_index:02d}_{digest[:12]}.mp4"
    storage.put_file(key, temp, "video/mp4")
    result = mediacheck.check(temp, reported_duration_ms=clip.duration_ms, clip_min_s=job.clip_min_s,
                              clip_max_s=job.clip_max_s)
    clip.storage_key, clip.uploaded_at = key, now()
    clip.check_status, clip.check_results = result["status"], result
    quota.settle_clip(db, job.workspace_id, job.id, job.quota_period, clip.clip_index)
    if job.review_mode == "auto" and result["status"] == "passed":
        _auto_approve(clip)


def edit_metadata(db: Session, job: Job, clip: Clip, user_id: uuid.UUID, expected_version: int,
                  caption: str | None, hashtags: list[str] | None) -> ClipMetadata:
    if expected_version != clip.metadata_version:
        raise ApiError(409, "VERSION_CONFLICT", "ข้อความถูกแก้ไขไปแล้ว กรุณาโหลดใหม่",
                       {"current_version": clip.metadata_version})
    cur = current_metadata(db, clip)
    new = ClipMetadata(
        workspace_id=clip.workspace_id, clip_id=clip.id, version=clip.metadata_version + 1,
        caption=cur.caption if caption is None else caption,
        hashtags=cur.hashtags if hashtags is None else normalize_hashtags(hashtags), created_by=user_id,
    )
    db.add(new)
    clip.metadata_version = new.version
    # Auto mode re-applies its policy to the new text; review mode needs a person again.
    if job.review_mode == "auto" and clip.check_status == "passed":
        _auto_approve(clip)
    return new


def approve(clip: Clip, job: Job, user_id: uuid.UUID, metadata_version: int) -> None:
    if job.state == "CANCELLED":
        raise ApiError(409, "JOB_NOT_ACTIVE", "งานนี้ถูกยกเลิกแล้ว")
    if clip.uploaded_at is None:
        raise ApiError(409, "CLIP_NOT_UPLOADED", "ยังไม่ได้รับไฟล์คลิปนี้จาก Agent")
    if clip.check_status == "failed":
        raise ApiError(409, "CHECKS_FAILED", "ไฟล์ไม่ผ่านการตรวจ (ขนาด/เสียง/ความยาว) อนุมัติไม่ได้")
    if metadata_version != clip.metadata_version:
        raise ApiError(409, "VERSION_CONFLICT", "ข้อความถูกแก้ไขไปแล้ว กรุณาตรวจเวอร์ชันล่าสุดก่อนอนุมัติ",
                       {"current_version": clip.metadata_version})
    clip.approved_metadata_version, clip.approved_sha256 = metadata_version, clip.render_sha256
    clip.approved_at, clip.approved_by, clip.approval_mode = now(), user_id, "manual"


def revoke_approval(clip: Clip) -> None:
    clip.approved_metadata_version = clip.approved_sha256 = clip.approved_at = None
    clip.approved_by = clip.approval_mode = None
