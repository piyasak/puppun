"""Web view of registered Agents: list with presence, deregister (PRD §6: users can see and
release old registrations, so an uninstall without cleanup never burns quota for good)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import agent_sessions, audit
from ..agent_sessions import AgentSession
from ..deps import WebAuth, get_db, web_auth
from ..models import AgentInstallation, Environment
from ..tenancy import get_owned, scoped

router = APIRouter(prefix="/v1/agents")


def _out(inst: AgentInstallation, env_name: str, live: AgentSession | None, at) -> dict:
    return {
        "id": str(inst.id),
        "installation_id": inst.installation_id,
        "environment": {"id": str(inst.environment_id), "name": env_name},
        "agent_version": inst.agent_version,
        "registered": inst.deregistered_at is None,
        "presence": agent_sessions.presence(live.last_heartbeat_at if live else None, live is not None, at),
        "last_seen_at": inst.last_seen_at.isoformat() if inst.last_seen_at else None,
        "created_at": inst.created_at.isoformat(),
        "deregistered_at": inst.deregistered_at.isoformat() if inst.deregistered_at else None,
    }


@router.get("")
def list_agents(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    at = agent_sessions.now()
    rows = db.execute(
        scoped(AgentInstallation, auth.workspace_id)
        .join(Environment, Environment.id == AgentInstallation.environment_id)
        .add_columns(Environment.name)
        .order_by(AgentInstallation.deregistered_at.is_not(None), AgentInstallation.created_at.desc())
    ).all()
    live = {
        s.installation_ref: s
        for s in db.scalars(
            scoped(AgentSession, auth.workspace_id).where(*agent_sessions.live_filter(at))
        ).all()
    }
    return {"items": [_out(inst, env_name, live.get(inst.id), at) for inst, env_name in rows]}


@router.post("/{agent_id}/deregister")
def deregister(agent_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
               db: Session = Depends(get_db)):
    """Frees the registration slot and ends any live session. Idempotent."""
    inst = get_owned(db, AgentInstallation, agent_id, auth.workspace_id, for_update=True)
    if inst.deregistered_at is None:
        inst.deregistered_at = agent_sessions.now()
        agent_sessions.end_sessions(db, AgentSession.installation_ref == inst.id, reason="deregistered")
        audit.record(db, request, "agent.deregister", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=inst.id)
    db.commit()
    env_name = db.get(Environment, inst.environment_id).name
    return _out(inst, env_name, None, agent_sessions.now())
