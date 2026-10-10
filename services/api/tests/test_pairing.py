"""Pairing codes (PO 2026-10-10): the web makes a short code, the Agent swaps it once for its own
Agent token. Wrong, used and expired codes look the same; the code is stored only as a hash."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from api_test_agents import Agent
from sqlalchemy import select, update

from clipflow_api.models import AgentPairingCode, AuditEvent


def env_of(acc, name="office"):
    return acc.post("/v1/environments", json={"name": f"{name}-{uuid.uuid4().hex[:6]}"}).json()


def test_code_links_a_pc_without_copying_a_token(onboard, client, app):
    acc = onboard()
    env = env_of(acc)
    made = acc.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]})
    assert made.status_code == 201 and made.headers["cache-control"] == "no-store"
    body = made.json()
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", body["code"]) and body["expires_in_s"] == 600

    paired = client.post("/v1/agent/pair", json={"code": body["code"].lower().replace("-", " "), "computer_name": "SHOP-PC"})
    assert paired.status_code == 200, paired.text
    got = paired.json()
    assert got["username"] == acc.username and got["environment"]["name"] == env["name"]
    assert paired.headers["cache-control"] == "no-store"
    # The token works like any Agent token, and shows on the Agent Token page under the PC's name
    agent = Agent(client, got["username"], got["token"])
    assert agent.auth().status_code == 200
    names = [t["name"] for t in acc.get("/v1/agent-tokens").json()["items"]]
    assert "PC SHOP-PC" in names

    with app.state.db.sessionmaker() as s:  # only a hash of the code is kept
        row = s.scalars(select(AgentPairingCode).where(AgentPairingCode.environment_id == uuid.UUID(env["id"]))).one()
        assert body["code"].replace("-", "") not in row.code_hash and row.used_at and row.token_id
        assert s.scalars(select(AuditEvent).where(AuditEvent.action == "agent_pairing_code.used")).first()


def test_used_expired_and_wrong_codes_get_the_same_answer(onboard, client, app):
    acc = onboard()
    env = env_of(acc)
    used = acc.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]}).json()["code"]
    assert client.post("/v1/agent/pair", json={"code": used}).status_code == 200
    old = acc.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]}).json()["code"]
    with app.state.db.sessionmaker() as s:
        s.execute(update(AgentPairingCode).where(AgentPairingCode.used_at.is_(None),
                                                 AgentPairingCode.environment_id == uuid.UUID(env["id"]))
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    answers = [client.post("/v1/agent/pair", json={"code": c}) for c in (used, old, "ABCD-EFGH")]
    assert {(r.status_code, r.json()["code"], r.json()["message"]) for r in answers} == {
        (400, "PAIRING_CODE_INVALID", answers[0].json()["message"])}


def test_only_for_your_own_environment(onboard):
    owner, other = onboard(), onboard()
    env = env_of(owner)
    assert other.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]}).status_code == 404


def test_open_codes_are_limited(onboard):
    acc = onboard()
    env = env_of(acc)
    codes = [acc.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]}).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_needs_a_signed_in_user(client):
    assert client.post("/v1/agent-pairing-codes", json={"environment_id": str(uuid.uuid4())}).status_code == 401


def test_agent_settings_pair_over_http(onboard, server_url, tmp_path, monkeypatch):
    """The settings window's pairing (agent/settings.py) against the real API: config + encrypted token saved."""
    from agent import settings
    from agent.credentials import load_config
    from agent.server_client import ServerClient

    saved = {}
    monkeypatch.setattr(settings, "save_token", lambda data, token: saved.update(token=token))
    acc = onboard()
    env = env_of(acc)
    code = acc.post("/v1/agent-pairing-codes", json={"environment_id": env["id"]}).json()["code"]
    result = settings.pair(tmp_path, server_url, code)
    assert result == {"username": acc.username, "environment": env["name"]}
    assert load_config(tmp_path).username == acc.username
    session = ServerClient(server_url).authenticate(acc.username, saved["token"], "settings-test-install")
    assert session.environment["name"] == env["name"]
    with pytest.raises(settings.SettingsError, match="รหัสเชื่อมต่อไม่ถูกต้อง"):
        settings.pair(tmp_path, server_url, code)  # once only
