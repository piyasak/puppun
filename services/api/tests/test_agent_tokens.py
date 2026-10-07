"""FR-12 / NF-02 / G2-02: Agent token generate (shown once), list, expiry, revoke, rotate, logs."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from clipflow_api import agent_tokens
from clipflow_api.models import AgentToken, AuditEvent


@pytest.fixture
def owner(onboard):
    acc = onboard()
    acc.env_id = acc.post("/v1/environments", json={"name": "office"}).json()["id"]
    return acc


def create(acc, **kw):
    return acc.post("/v1/agent-tokens", json={"environment_id": acc.env_id, "name": "PC หน้าร้าน"} | kw)


def secret_of(token: str) -> str:
    # The base64url secret may itself contain "_", so parse with the format regex, not split().
    return agent_tokens.TOKEN_RE.match(token).group(2)


def db(app):
    return app.state.db.sessionmaker()


def test_token_is_shown_once_and_only_its_hash_is_stored(owner, app):
    resp = create(owner)
    assert resp.status_code == 201
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    token = body["token"]
    assert agent_tokens.TOKEN_RE.match(token) and body["prefix"] in token
    assert body["status"] == "active" and body["environment"]["name"] == "office"

    listed = owner.get("/v1/agent-tokens").json()["items"]
    assert [t["id"] for t in listed] == [body["id"]]
    assert "token" not in listed[0] and token not in str(listed)

    with db(app) as s:
        row = s.get(AgentToken, uuid.UUID(body["id"]))
        assert row.secret_hash == agent_tokens.hash_token(token) and token not in row.secret_hash
        secret_part = secret_of(token)
        for table_row in s.scalars(select(AgentToken)).all():
            assert secret_part not in (table_row.secret_hash + table_row.prefix + table_row.name)


def test_tokens_have_256_bit_secrets_and_unique_prefixes():
    tokens = [agent_tokens.generate()[0] for _ in range(200)]
    assert len({agent_tokens.TOKEN_RE.match(t).group(1) for t in tokens}) == 200
    assert all(len(secret_of(t)) == 43 for t in tokens)  # 32 random bytes, base64url


def test_expiry_bounds_and_default(owner):
    assert create(owner, expires_in_days=0).status_code == 422
    assert create(owner, expires_in_days=366).status_code == 422
    body = create(owner).json()
    days = (datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(body["created_at"])).days
    assert days in (89, 90)


def test_verify_accepts_owner_and_rejects_everything_else(owner, onboard, app):
    token = create(owner).json()["token"]
    other = onboard()
    with db(app) as s:
        scope = agent_tokens.verify(s, owner.username.upper(), token)
        assert str(scope.environment_id) == owner.env_id
        bad = [
            (other.username, token),                       # T02: someone else's username
            (owner.username, token[:-1] + ("A" if token[-1] != "A" else "B")),  # wrong secret
            (owner.username, "cfat_" + "z" * 10 + "_" + "x" * 43),  # unknown prefix
            (owner.username, "not-a-token"),
            (owner.username, ""),
        ]
        for username, candidate in bad:
            with pytest.raises(agent_tokens.TokenRejected):
                agent_tokens.verify(s, username, candidate)


def test_expired_token_is_rejected(owner, app):
    body = create(owner).json()
    with db(app) as s:
        s.execute(update(AgentToken).where(AgentToken.id == uuid.UUID(body["id"]))
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
        with pytest.raises(agent_tokens.TokenRejected):
            agent_tokens.verify(s, owner.username, body["token"])
    assert owner.get("/v1/agent-tokens").json()["items"][0]["status"] == "expired"


def test_revoke_is_immediate_idempotent_and_audited(owner, app):
    body = create(owner).json()
    first = owner.post(f"/v1/agent-tokens/{body['id']}/revoke").json()
    again = owner.post(f"/v1/agent-tokens/{body['id']}/revoke").json()
    assert first["status"] == again["status"] == "revoked" and first["revoked_at"] == again["revoked_at"]
    with db(app) as s:
        with pytest.raises(agent_tokens.TokenRejected):
            agent_tokens.verify(s, owner.username, body["token"])
        actions = s.scalars(select(AuditEvent.action).where(AuditEvent.target_id == uuid.UUID(body["id"]))).all()
        assert actions.count("agent_token.revoke") == 1


def test_rotate_issues_a_new_token_and_revokes_the_old(owner, app):
    old = create(owner).json()
    resp = owner.post(f"/v1/agent-tokens/{old['id']}/rotate")
    assert resp.status_code == 201 and resp.headers["cache-control"] == "no-store"
    new = resp.json()
    assert new["token"] != old["token"] and new["rotated_from_id"] == old["id"]
    assert new["environment"]["id"] == old["environment"]["id"] and new["name"] == old["name"]
    with db(app) as s:
        assert agent_tokens.verify(s, owner.username, new["token"])
        with pytest.raises(agent_tokens.TokenRejected):
            agent_tokens.verify(s, owner.username, old["token"])
    assert owner.post(f"/v1/agent-tokens/{old['id']}/rotate").json()["code"] == "TOKEN_REVOKED"


def test_tokens_are_tenant_scoped(owner, onboard):
    body = create(owner).json()
    other = onboard()
    assert other.get("/v1/agent-tokens").json()["items"] == []
    assert other.post(f"/v1/agent-tokens/{body['id']}/revoke").status_code == 404
    assert other.post(f"/v1/agent-tokens/{body['id']}/rotate").status_code == 404
    # Cannot mint a token for another Workspace's Environment
    resp = other.post("/v1/agent-tokens", json={"environment_id": owner.env_id, "name": "x"})
    assert resp.status_code == 404
    assert owner.get("/v1/agent-tokens").json()["items"][0]["status"] == "active"


def test_agent_token_is_not_a_web_credential(owner, client):
    token = create(owner).json()["token"]
    resp = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_active_tokens_per_environment_are_capped(owner):
    for i in range(10):
        assert create(owner, name=f"t{i}").status_code == 201
    assert create(owner, name="t10").json()["code"] == "TOKEN_LIMIT"


def test_tokens_never_reach_logs_or_audit(owner, app, caplog):
    caplog.set_level(logging.DEBUG)
    created = create(owner).json()
    rotated = owner.post(f"/v1/agent-tokens/{created['id']}/rotate").json()
    owner.post(f"/v1/agent-tokens/{rotated['id']}/revoke")
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "request_id=" in log_text
    for token in (created["token"], rotated["token"]):
        secret = secret_of(token)
        assert token not in log_text and secret not in log_text
        with db(app) as s:
            for event in s.scalars(select(AuditEvent)).all():
                assert secret not in f"{event.action}{event.target_id}{event.request_id}"
