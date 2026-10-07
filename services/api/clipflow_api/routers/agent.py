"""Agent-facing API (outbound HTTPS polling from the customer's Windows Agent).

Auth is separate from the browser: `/agent/authenticate` takes username + Agent token +
installation_id and returns a short-lived session token (`cfas_…`) used as
`Authorization: Bearer` on the other Agent calls. Supabase browser tokens are not accepted
here, and Agent sessions are not accepted by the web API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import agent_sessions, audit
from ..agent_sessions import AgentContext
from ..deps import get_db
from ..models import Environment

router = APIRouter(prefix="/v1/agent")


class AuthenticateIn(BaseModel):
    # Unknown fields (e.g. a client-supplied "environment") are ignored, never trusted (T05).
    model_config = ConfigDict(extra="ignore")

    username: str = Field(min_length=1, max_length=32)
    token: str = Field(min_length=1, max_length=200)
    installation_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    agent_version: str | None = Field(default=None, max_length=32)


class HeartbeatIn(BaseModel):
    generation: int = Field(ge=1)


def agent_context(request: Request, db: Session = Depends(get_db)) -> AgentContext:
    scheme, _, raw = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not raw:
        raise agent_sessions.session_ended("invalid")
    return agent_sessions.resolve(db, raw.strip())


def _session_out(new_or_session, env_name: str, generation: int) -> dict:
    s = new_or_session
    return {
        "generation": generation,
        "expires_at": s.expires_at.isoformat(),
        "heartbeat_interval_s": agent_sessions.HEARTBEAT_INTERVAL_S,
        "environment": {"id": str(s.environment_id), "name": env_name},
    }


@router.post("/authenticate")
def authenticate(body: AuthenticateIn, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "unknown"
    request.app.state.agent_auth_limiter.hit(client)
    new = agent_sessions.authenticate(db, body.username, body.token, body.installation_id, body.agent_version)
    audit.record(db, request, "agent.session.start", workspace_id=new.environment.workspace_id,
                 target_id=new.installation.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"session_token": new.session_token, "installation_ref": str(new.installation.id),
            **_session_out(new.session, new.environment.name, new.session.generation)}


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    s = agent_sessions.heartbeat(db, ctx, body.generation)
    db.commit()
    return _session_out(s, db.get(Environment, ctx.environment_id).name, ctx.generation)


@router.post("/session/end", status_code=204)
def end_session(request: Request, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    agent_sessions.end_sessions(db, agent_sessions.AgentSession.id == ctx.session_id, reason="agent_exit")
    audit.record(db, request, "agent.session.end", workspace_id=ctx.workspace_id, target_id=ctx.installation_ref)
    db.commit()
