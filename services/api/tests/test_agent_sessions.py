"""FR-14 / G2-03: Agent authenticate, heartbeat, fencing, registration and session limits.

UAT ids: T02 wrong username, T03 reconnect x20, T04 two processes one installation,
T05 client-supplied Environment ignored. Revoke-during-Submit (T06) belongs to P5.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from api_test_agents import Agent
from api_test_tokens import SIGNING_KEY, SUPABASE_URL
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from clipflow_api.app import create_app
from clipflow_api.config import Settings
from clipflow_api.models import AgentInstallation, AgentSession, AgentToken


@pytest.fixture
def setup(onboard, client):
    """Owner with one Environment (limits 2 agents / 1 session) and one token."""
    acc = onboard()
    env = acc.post("/v1/environments", json={"name": "office", "registered_agent_limit": 2,
                                             "concurrent_session_limit": 1, "device_limit": 1}).json()
    tok = acc.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()
    acc.env, acc.tok = env, tok
    acc.agent = lambda installation_id=None: Agent(client, acc.username, tok["token"], installation_id)
    return acc


def db(app):
    return app.state.db.sessionmaker()


def strip(resp):
    return {k: v for k, v in resp.json().items() if k != "request_id"}


def test_authenticate_returns_session_scoped_to_the_token_environment(setup):
    a = setup.agent()
    resp = a.auth(environment="someone-elses-env", environment_id=str(uuid.uuid4()))  # T05: ignored
    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["session_token"].startswith("cfas_") and body["generation"] == 1
    assert body["environment"] == {"id": setup.env["id"], "name": "office"}
    assert body["heartbeat_interval_s"] == 15
    assert "clip_preview" in body["features"]  # Q-33: Agents only take jobs from servers that can take kept clips
    assert a.heartbeat().status_code == 200


def test_wrong_username_unknown_and_revoked_tokens_look_the_same(setup, onboard, client):
    other = onboard()
    wrong_user = Agent(client, other.username, setup.tok["token"]).auth()  # T02
    unknown = Agent(client, setup.username, "cfat_" + "a" * 10 + "_" + "b" * 43).auth()
    setup.post(f"/v1/agent-tokens/{setup.tok['id']}/revoke")
    revoked = setup.agent().auth()
    assert wrong_user.status_code == unknown.status_code == revoked.status_code == 401
    assert strip(wrong_user) == strip(unknown) == strip(revoked)
    assert other.username not in wrong_user.text and "office" not in wrong_user.text


def test_reconnect_twenty_times_keeps_one_registration(setup, app):  # T03
    a = setup.agent()
    for _ in range(20):
        assert a.auth().status_code == 200
    assert a.generation == 20
    with db(app) as s:
        inst = s.scalars(select(AgentInstallation).where(AgentInstallation.installation_id == a.installation_id)).all()
        assert len(inst) == 1
        live = s.scalar(select(func.count()).select_from(AgentSession).where(
            AgentSession.installation_ref == inst[0].id, AgentSession.ended_at.is_(None)))
        assert live == 1
    assert setup.get("/v1/workspace/usage").json()["in_use"]["registered_agent_limit"] == 1


def test_second_process_with_same_installation_fences_the_first(setup):  # T04
    first = setup.agent()
    second = setup.agent(first.installation_id)
    assert first.auth().status_code == 200
    assert second.auth().status_code == 200
    stale = first.heartbeat()
    assert stale.status_code == 401 and stale.json()["details"]["reason"] == "superseded"
    assert second.heartbeat().status_code == 200
    # A stale generation on the current session is refused too.
    assert second.heartbeat(generation=second.generation - 1).json()["code"] == "STALE_GENERATION"


def test_registered_agent_limit_and_deregistration(setup, client):
    setup.patch(f"/v1/environments/{setup.env['id']}", json={"registered_agent_limit": 1})
    x, y = setup.agent(), setup.agent()
    assert x.auth().status_code == 200
    blocked = y.auth()
    assert blocked.status_code == 409 and blocked.json()["code"] == "AGENT_LIMIT_REACHED"

    agents = setup.get("/v1/agents").json()["items"]
    assert [(g["installation_id"], g["presence"]) for g in agents] == [(x.installation_id, "online")]
    assert setup.post(f"/v1/agents/{agents[0]['id']}/deregister").json()["registered"] is False
    assert x.heartbeat().json()["details"]["reason"] == "deregistered"
    assert y.auth().status_code == 200


def test_concurrent_session_limit_and_rollback_on_refusal(setup, app):
    x, y = setup.agent(), setup.agent()
    assert x.auth().status_code == 200
    full = y.auth()
    assert full.status_code == 409 and full.json()["code"] == "SESSION_LIMIT_REACHED"
    with db(app) as s:  # the refused attempt did not keep a registration
        assert s.scalar(select(func.count()).select_from(AgentInstallation).where(
            AgentInstallation.installation_id == y.installation_id)) == 0
    assert x.heartbeat().status_code == 200  # x is unaffected
    x.client.post("/v1/agent/session/end", headers={"Authorization": f"Bearer {x.session}"})
    assert y.auth().status_code == 200


def test_expired_session_frees_its_slot(setup, app):
    x, y = setup.agent(), setup.agent()
    x.auth()
    with db(app) as s:
        s.execute(update(AgentSession).where(AgentSession.generation == 1, AgentSession.ended_at.is_(None),
                                             AgentSession.environment_id == uuid.UUID(setup.env["id"]))
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    assert x.heartbeat().json()["details"]["reason"] == "expired"
    assert y.auth().status_code == 200


def test_revoke_and_rotate_end_live_sessions_immediately(setup, app):
    a = setup.agent()
    a.auth()
    new = setup.post(f"/v1/agent-tokens/{setup.tok['id']}/rotate").json()
    with db(app) as s:
        ended = s.scalars(select(AgentSession.end_reason).where(
            AgentSession.token_id == uuid.UUID(setup.tok["id"]))).all()
        assert ended == ["token_revoked"]
    assert a.heartbeat().json()["details"]["reason"] == "token_revoked"
    a.token = new["token"]
    assert a.auth().status_code == 200  # same installation, new token: still one registration


def test_expired_token_ends_the_session_on_next_call(setup, app):
    a = setup.agent()
    a.auth()
    with db(app) as s:
        s.execute(update(AgentToken).where(AgentToken.id == uuid.UUID(setup.tok["id"]))
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    assert a.heartbeat().json()["details"]["reason"] == "token_revoked"


def test_lowering_limits_below_usage_is_refused(setup):
    setup.agent().auth()
    resp = setup.patch(f"/v1/environments/{setup.env['id']}", json={"registered_agent_limit": 0,
                                                                     "concurrent_session_limit": 0})
    assert resp.status_code == 409 and resp.json()["code"] == "LIMIT_BELOW_USAGE"


def test_credentials_do_not_cross_between_web_and_agent(setup, client):
    a = setup.agent()
    a.auth()
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {a.session}"}).status_code == 401
    web_token = setup.headers()["Authorization"]
    resp = client.post("/v1/agent/heartbeat", json={"generation": 1}, headers={"Authorization": web_token})
    assert resp.status_code == 401


def test_agents_are_tenant_scoped(setup, onboard):
    setup.agent().auth()
    other = onboard()
    assert other.get("/v1/agents").json()["items"] == []
    agent_id = setup.get("/v1/agents").json()["items"][0]["id"]
    assert other.post(f"/v1/agents/{agent_id}/deregister").status_code == 404
    assert setup.get("/v1/agents").json()["items"][0]["registered"] is True


def test_installation_id_format_is_validated(setup):
    assert setup.agent("bad id with spaces").auth().status_code == 422


def test_agent_sign_in_is_rate_limited(migrated_url, onboard):
    limited = create_app(Settings(app_env="test", database_url=migrated_url, supabase_url=SUPABASE_URL,
                                  agent_auth_rate_per_minute=5),
                         resolve_key=lambda token: SIGNING_KEY.public_key())
    c = TestClient(limited)
    codes = [Agent(c, "nobody", "cfat_x").auth().status_code for _ in range(7)]
    assert codes == [401] * 5 + [429, 429]


def test_session_tokens_never_reach_logs(setup, caplog):
    caplog.set_level(logging.DEBUG)
    a = setup.agent()
    a.auth()
    a.heartbeat()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "request_id=" in text and a.session not in text and setup.tok["token"] not in text


def test_simultaneous_new_installations_cannot_overshoot_the_limit(setup, app):
    """Five new installs at once against registered_agent_limit = 2 (sessions 2)."""
    from concurrent.futures import ThreadPoolExecutor

    assert setup.patch(f"/v1/environments/{setup.env['id']}", json={"concurrent_session_limit": 2}).status_code == 200

    def connect(_):
        with TestClient(app) as c:
            return Agent(c, setup.username, setup.tok["token"]).auth().status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = sorted(pool.map(connect, range(5)))
    assert codes == [200, 200, 409, 409, 409]
    usage = setup.get("/v1/workspace/usage").json()["in_use"]
    assert usage == {"registered_agent_limit": 2, "concurrent_session_limit": 2, "device_limit": 0}
