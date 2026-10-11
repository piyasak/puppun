"""What is in the Agent's videos folder (PO 2026-10-11), so the web can offer it when a job is made.

- Full videos sit at the top of the folder: the Agent cuts them by the job's settings (source local_file).
- Each sub-folder holds clips already cut, in EP order: the Agent sends them as they are (local_clips).

The Agent reports names and sizes only (never paths, never the files). The latest report per Environment
is kept; the web reads it to fill the lists on /create.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..agent_sessions import AgentContext
from ..deps import WebAuth, get_db, web_auth
from ..models import AgentLibrary, Environment
from ..sources import FILE_NAME_RE, VIDEO_EXTENSIONS
from ..tenancy import get_owned
from .agent import agent_context

agent_router = APIRouter(prefix="/v1/agent/library")
web_router = APIRouter(prefix="/v1/environments")

MAX_VIDEOS = 500
MAX_SETS = 200
MAX_CLIPS = 100  # jobs.AUTO_MAX_CLIPS: one job takes at most this many clips


class VideoIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=200)
    size_bytes: int = Field(ge=0)
    modified_at: datetime | None = None


class SetIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    folder: str = Field(max_length=200)
    clips: list[str] = Field(default_factory=list, max_length=1000)
    size_bytes: int = Field(default=0, ge=0)


class LibraryIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    videos: list[VideoIn] = Field(default_factory=list, max_length=5000)
    sets: list[SetIn] = Field(default_factory=list, max_length=2000)


def _bare(name: str) -> bool:
    return bool(FILE_NAME_RE.match(name)) and name not in (".", "..")


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


@agent_router.put("")
def report_library(body: LibraryIn, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    videos = [{"name": v.name, "size_bytes": v.size_bytes,
               "modified_at": v.modified_at.isoformat() if v.modified_at else None}
              for v in body.videos if _bare(v.name) and v.name.lower().endswith(VIDEO_EXTENSIONS)]
    videos.sort(key=lambda v: _natural(v["name"]))
    sets = []
    for s in body.sets:
        clips = sorted((c for c in s.clips if _bare(c) and c.lower().endswith(".mp4")), key=_natural)
        if _bare(s.folder) and clips:
            sets.append({"folder": s.folder, "count": len(clips), "clips": clips[:MAX_CLIPS],
                         "too_many": len(clips) > MAX_CLIPS, "size_bytes": s.size_bytes})
    sets.sort(key=lambda s: _natural(s["folder"]))
    row = db.get(AgentLibrary, ctx.environment_id)
    if row is None:
        row = AgentLibrary(environment_id=ctx.environment_id, workspace_id=ctx.workspace_id)
        db.add(row)
    row.installation_ref, row.videos, row.sets = ctx.installation_ref, videos[:MAX_VIDEOS], sets[:MAX_SETS]
    row.reported_at = datetime.now(UTC)
    db.commit()
    return {"videos": len(row.videos), "sets": len(row.sets)}


@web_router.get("/{environment_id}/library")
def library(environment_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    get_owned(db, Environment, environment_id, auth.workspace_id)  # 404 for another tenant's Environment
    row = db.get(AgentLibrary, environment_id)
    if row is None:
        return {"reported_at": None, "videos": [], "sets": []}
    return {"reported_at": row.reported_at.isoformat(), "videos": row.videos, "sets": row.sets}
