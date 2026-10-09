"""Jobs: web create/list/detail/cancel and the Agent claim/events protocol (P3.1)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, jobs, quota
from ..agent_sessions import AgentContext
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import Clip, Environment, Job
from ..tenancy import get_owned, scoped
from .agent import agent_context

web_router = APIRouter(prefix="/v1/jobs")
agent_router = APIRouter(prefix="/v1/agent/jobs")


class SourceIn(BaseModel):
    kind: Literal["url", "local_file"]
    url: str | None = Field(default=None, max_length=500)
    file_name: str | None = Field(default=None, max_length=200)


class JobIn(BaseModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    environment_id: uuid.UUID
    source: SourceIn
    requested_clips: int = Field(default=3, ge=1, le=20)
    # Q-32: the count follows the source (the whole source is split); requested_clips is then ignored.
    auto_clips: bool = False
    clip_min_s: int = Field(default=180, ge=15, le=600)  # D02: 3-5 minutes
    clip_max_s: int = Field(default=300, ge=15, le=600)
    # Q-32: one length instead of a range: clips of 80-100 % of it, cut at pauses (default 300 s in the UI).
    clip_length_s: int | None = Field(default=None, ge=15, le=600)
    subtitles: bool = True  # Q-12
    review_mode: Literal["review", "auto"] = "review"
    confirm_auto: bool = False  # FR-08: auto mode must be switched on explicitly

    @model_validator(mode="after")
    def _check(self):
        if self.clip_length_s is not None:
            self.clip_max_s = self.clip_length_s
            self.clip_min_s = max(15, round(self.clip_length_s * 0.8))
        if self.clip_min_s > self.clip_max_s:
            raise ValueError("clip_min_s_above_clip_max_s")
        if self.review_mode == "auto" and not self.confirm_auto:
            raise ValueError("auto_mode_requires_confirm_auto")
        return self


def job_out(db: Session, job: Job, *, with_clips: bool = False) -> dict:
    out = {
        "id": str(job.id),
        "state": job.state,
        "state_version": job.state_version,
        "source": {"kind": job.source_kind, "url": job.source_url, "file_name": job.source_label},
        "environment_id": str(job.environment_id),
        "requested_clips": job.requested_clips,
        "auto_clips": job.auto_clips,
        "planned_clips": job.planned_clips,
        "clip_min_s": job.clip_min_s,
        "clip_max_s": job.clip_max_s,
        "subtitles": job.subtitles,
        "review_mode": job.review_mode,
        "seed": job.seed,
        "notice": job.notice,
        "error": {"code": job.error_code, "detail": job.error_detail} if job.error_code else None,
        "source_duration_s": job.source_duration_s,
        "quota": quota.job_balance(db, job.id),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
    if with_clips:
        from .clips import clip_out  # clip detail shape is owned by the clips router

        rows = db.scalars(select(Clip).where(Clip.job_id == job.id).order_by(Clip.clip_index)).all()
        out["clips"] = [clip_out(db, c, job) for c in rows]
    return out


@web_router.post("")
def create_job(body: JobIn, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    job, created = jobs.create(
        db, workspace_id=auth.workspace_id, user_id=auth.user_id, environment_id=body.environment_id,
        idempotency_key=body.idempotency_key, source=body.source.model_dump(),
        requested_clips=jobs.AUTO_MAX_CLIPS if body.auto_clips else body.requested_clips, auto_clips=body.auto_clips,
        clip_min_s=body.clip_min_s, clip_max_s=body.clip_max_s, subtitles=body.subtitles, review_mode=body.review_mode,
    )
    if created:
        audit.record(db, request, "job.create", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=job.id)
    db.commit()
    # 201 for a new job, 200 when the idempotency key matched an existing one.
    return JSONResponse(job_out(db, job), status_code=201 if created else 200)


@web_router.get("")
def list_jobs(state: str | None = None, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    stmt = scoped(Job, auth.workspace_id).order_by(Job.created_at.desc()).limit(100)
    if state:
        stmt = stmt.where(Job.state == state)
    return {"items": [job_out(db, j) for j in db.scalars(stmt).all()]}


@web_router.get("/{job_id}")
def get_job(job_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return job_out(db, get_owned(db, Job, job_id, auth.workspace_id), with_clips=True)


@web_router.post("/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    job = get_owned(db, Job, job_id, auth.workspace_id, for_update=True)
    jobs.cancel(db, job)
    audit.record(db, request, "job.cancel", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=job.id)
    db.commit()
    return job_out(db, job)


# --- Agent ----------------------------------------------------------------------------------

class EventIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    type: str = Field(max_length=32)


def _spec(db: Session, job: Job, env_name: str) -> dict:
    # Clips already reported let a restarted Agent resume instead of starting over (E-37).
    reported = db.scalars(select(Clip).where(Clip.job_id == job.id).order_by(Clip.clip_index)).all()
    return {
        "clips": [{"index": c.clip_index, "sha256": c.render_sha256, "uploaded": c.uploaded_at is not None}
                  for c in reported],
        "id": str(job.id), "state": job.state, "state_version": job.state_version,
        "environment": {"id": str(job.environment_id), "name": env_name},
        "source": {"kind": job.source_kind, "url": job.source_url, "file_name": job.source_label},
        "requested_clips": job.requested_clips, "planned_clips": job.planned_clips, "auto_clips": job.auto_clips,
        "clip_min_s": job.clip_min_s, "clip_max_s": job.clip_max_s, "subtitles": job.subtitles,
        "seed": job.seed, "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
    }


@agent_router.post("/claim")
def claim_job(ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    job = jobs.claim(db, ctx)
    db.commit()
    if job is None:
        return {"job": None}
    return {"job": _spec(db, job, db.get(Environment, job.environment_id).name)}


@agent_router.post("/{job_id}/events")
def job_event(job_id: uuid.UUID, body: EventIn, ctx: AgentContext = Depends(agent_context),
              db: Session = Depends(get_db)):
    try:
        job, duplicate = jobs.apply_event(db, ctx, job_id, body.model_dump())
    except (KeyError, TypeError, ValueError) as exc:
        db.rollback()
        raise ApiError(422, "VALIDATION_ERROR", "ข้อมูล event ไม่ครบหรือไม่ถูกต้อง", {"missing_or_bad": str(exc)}) from None
    db.commit()
    return {"duplicate": duplicate, "job": _spec(db, job, db.get(Environment, job.environment_id).name)}
