"""Agent side of posting: claim a due post, report its progress (P4.3, E-40)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import posts
from ..agent_sessions import AgentContext
from ..deps import get_db
from .agent import agent_context

agent_router = APIRouter(prefix="/v1/agent/posts")


class ClaimIn(BaseModel):
    # Phones this Agent can reach right now (ADB state "device"); only their posts are offered.
    ready_serials: list[str] = Field(default_factory=list, max_length=50)
    # Q-42: Agents from 0.4.0 can carry out a live post under a server grant; older ones never get one.
    can_post_live: bool = False


class EventIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    type: str = Field(max_length=24)


@agent_router.post("/claim")
def claim(body: ClaimIn, request: Request, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    item = posts.claim(db, ctx, body.ready_serials, can_post_live=body.can_post_live,
                       server_mode=request.app.state.posting_mode)
    db.commit()  # parked/deferred/expired items are kept even when nothing is handed out
    if item is None:
        return {"post": None}
    state = request.app.state
    return {"post": posts.spec(db, item, state.storage, state.settings.preview_ttl_s, state.posting_mode)}


@agent_router.post("/{item_id}/events")
def event(item_id: uuid.UUID, body: EventIn, request: Request, ctx: AgentContext = Depends(agent_context),
          db: Session = Depends(get_db)):
    item, duplicate, refusal = posts.apply_event(db, ctx, item_id, body.model_dump(), request.app.state.posting_mode)
    db.commit()
    if refusal:
        raise refusal
    return {"duplicate": duplicate, "state": item.state, "state_version": item.state_version,
            "lease_expires_at": item.lease_expires_at.isoformat() if item.lease_expires_at else None}
