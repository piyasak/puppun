"""Clip upload (Agent), detail/preview/metadata/approval (web) and local preview serving (P3.2)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clips, jobs, schedules
from ..agent_sessions import AgentContext
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError, not_found
from ..models import Clip, ClipMetadata, Job
from ..storage import LocalStorage
from ..tenancy import get_owned
from .agent import agent_context

agent_router = APIRouter(prefix="/v1/agent/jobs")
web_router = APIRouter(prefix="/v1/clips")
media_router = APIRouter(prefix="/v1/media")


def clip_out(db: Session, clip: Clip, job: Job) -> dict:
    meta = clips.current_metadata(db, clip)
    return {
        "id": str(clip.id), "job_id": str(clip.job_id), "index": clip.clip_index,
        "title": clip.title, "start_ms": clip.start_ms, "end_ms": clip.end_ms, "duration_ms": clip.duration_ms,
        "seed": clip.seed, "template_version": clip.template_version, "render_sha256": clip.render_sha256,
        "size_bytes": clip.size_bytes, "uploaded": clip.uploaded_at is not None,
        "checks": clip.check_results, "check_status": clip.check_status,
        "metadata": {"version": meta.version, "caption": meta.caption, "hashtags": meta.hashtags},
        "review_mode": job.review_mode,
        "approval": {
            "approved": clips.is_approved(clip), "metadata_version": clip.approved_metadata_version,
            "mode": clip.approval_mode, "at": clip.approved_at.isoformat() if clip.approved_at else None,
        },
    }


# --- Agent upload ---------------------------------------------------------------------------------

@agent_router.put("/{job_id}/clips/{index}/file")
async def upload_clip(job_id: uuid.UUID, index: int, request: Request, ctx: AgentContext = Depends(agent_context),
                      db: Session = Depends(get_db)):
    """Raw MP4 body. Streamed to a temp file and hashed here; never trusted from the Agent."""
    limit = request.app.state.settings.max_clip_bytes
    fd, name = tempfile.mkstemp(prefix="clip-", suffix=".mp4")
    temp, digest, size = Path(name), hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise ApiError(413, "CLIP_TOO_LARGE", "ไฟล์คลิปใหญ่เกินกำหนด")
                digest.update(chunk)
                out.write(chunk)

        def store() -> dict:
            job = jobs.lease_holder_job(db, ctx, job_id)
            clip = db.scalars(select(Clip).where(Clip.job_id == job.id, Clip.clip_index == index)
                              .with_for_update()).first()
            if clip is None:
                raise ApiError(404, "NOT_FOUND", "ยังไม่ได้รายงานคลิปลำดับนี้ (clip_rendered)")
            clips.accept_upload(db, request.app.state.storage, job, clip, temp, size, digest.hexdigest())
            db.commit()
            return {"clip_id": str(clip.id), "check_status": clip.check_status,
                    "approved": clips.is_approved(clip)}

        return await run_in_threadpool(store)
    finally:
        temp.unlink(missing_ok=True)


# --- web ----------------------------------------------------------------------------------------

class MetadataPatch(BaseModel):
    expected_version: int = Field(ge=1)
    caption: str | None = Field(default=None, max_length=2200)
    hashtags: list[str] | None = Field(default=None, max_length=60)
    title: str | None = None  # refused: burned into the video


class ApproveIn(BaseModel):
    metadata_version: int = Field(ge=1)


def _owned(db: Session, auth: WebAuth, clip_id: uuid.UUID, *, lock: bool = False) -> tuple[Clip, Job]:
    clip = get_owned(db, Clip, clip_id, auth.workspace_id, for_update=lock)
    return clip, db.get(Job, clip.job_id)


@web_router.get("/{clip_id}")
def get_clip(clip_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    clip, job = _owned(db, auth, clip_id)
    out = clip_out(db, clip, job)
    out["metadata_history"] = [
        {"version": m.version, "caption": m.caption, "hashtags": m.hashtags, "created_at": m.created_at.isoformat()}
        for m in db.scalars(select(ClipMetadata).where(ClipMetadata.clip_id == clip.id)
                            .order_by(ClipMetadata.version.desc())).all()
    ]
    return out


@web_router.get("/{clip_id}/media")
def clip_media(clip_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """Short-lived preview link for the owner only (PRD §E)."""
    clip, _ = _owned(db, auth, clip_id)
    if clip.file_deleted_at is not None:
        raise ApiError(410, "CLIP_FILE_EXPIRED", "ไฟล์คลิปนี้ถูกลบตามระยะเวลาเก็บไฟล์ของแพ็กเกจแล้ว")
    if clip.storage_key is None:
        raise ApiError(409, "CLIP_NOT_UPLOADED", "ยังไม่ได้รับไฟล์คลิปนี้จาก Agent")
    ttl = request.app.state.settings.preview_ttl_s
    return {"url": request.app.state.storage.preview_url(clip.storage_key, ttl), "expires_in_s": ttl}


@web_router.patch("/{clip_id}/metadata")
def patch_metadata(clip_id: uuid.UUID, body: MetadataPatch, request: Request, auth: WebAuth = Depends(web_auth),
                   db: Session = Depends(get_db)):
    if body.title is not None:
        raise ApiError(409, "RERENDER_REQUIRED", "ชื่อคลิปอยู่ในวิดีโอ ต้องสร้างคลิปใหม่เพื่อเปลี่ยนชื่อ")
    clip, job = _owned(db, auth, clip_id, lock=True)
    clips.edit_metadata(db, job, clip, auth.user_id, body.expected_version, body.caption, body.hashtags)
    schedules.sync_clip_items(db, clip)  # scheduled posts follow only an approved version (G3-05)
    audit.record(db, request, "clip.metadata.edit", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=clip.id)
    db.commit()
    return clip_out(db, clip, job)


@web_router.post("/{clip_id}/approve")
def approve_clip(clip_id: uuid.UUID, body: ApproveIn, request: Request, auth: WebAuth = Depends(web_auth),
                 db: Session = Depends(get_db)):
    clip, job = _owned(db, auth, clip_id, lock=True)
    clips.approve(clip, job, auth.user_id, body.metadata_version)
    schedules.sync_clip_items(db, clip)
    audit.record(db, request, "clip.approve", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=clip.id)
    db.commit()
    return clip_out(db, clip, job)


@web_router.post("/{clip_id}/unapprove")
def unapprove_clip(clip_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                   db: Session = Depends(get_db)):
    clip, job = _owned(db, auth, clip_id, lock=True)
    clips.revoke_approval(clip)
    schedules.sync_clip_items(db, clip)
    audit.record(db, request, "clip.unapprove", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=clip.id)
    db.commit()
    return clip_out(db, clip, job)


@media_router.get("/{key:path}")
def local_media(key: str, exp: int, sig: str, request: Request):
    """Signed, expiring preview for LocalStorage. FileResponse serves Range requests (seeking)."""
    storage = request.app.state.storage
    if not isinstance(storage, LocalStorage):
        raise not_found()
    path = storage.verify(key, exp, sig)
    if path is None:
        raise not_found()
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=60"})
