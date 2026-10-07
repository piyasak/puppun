"""FR-01 / G2-01 (API side): Supabase token verification, onboarding and /me.

Sign-up, login and password reset themselves run in Supabase Auth; see test_supabase_live.py.
"""

from __future__ import annotations

import logging
import time
import uuid

import jwt
import pytest
from api_test_tokens import OTHER_KEY, SIGNING_KEY, mint, new_identity
from sqlalchemy import select

from clipflow_api.models import RightsAcceptance


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _strip(resp):
    return {k: v for k, v in resp.json().items() if k != "request_id"}


def test_onboarding_creates_owner_workspace_and_rights_acceptance(onboard, app):
    acc = onboard(workspace_name="ร้านทดสอบ")
    assert acc.body["role"] == "owner"
    assert acc.body["workspace"] == acc.body["workspace"] | {"name": "ร้านทดสอบ", "timezone": "Asia/Bangkok"}
    assert acc.body["user"]["id"] == str(acc.user_id)  # profile id = Supabase user id
    assert acc.body["rights_declaration"]["version"]
    assert acc.get("/v1/me").json()["user"]["username"] == acc.username
    with app.state.db.sessionmaker() as db:
        assert db.scalars(select(RightsAcceptance).where(RightsAcceptance.user_id == acc.user_id)).one()


def test_signed_in_but_not_onboarded_user_is_sent_to_onboarding(client):
    user_id, email = new_identity()
    resp = client.get("/v1/me", headers=bearer(mint(user_id, email)))
    assert resp.status_code == 403 and resp.json()["code"] == "ONBOARDING_REQUIRED"


def test_onboarding_requires_rights_declaration(client):
    user_id, email = new_identity()
    resp = client.post("/v1/onboarding", json={"username": "norights1", "accept_rights": False},
                       headers=bearer(mint(user_id, email)))
    assert resp.status_code == 422 and resp.json()["code"] == "RIGHTS_NOT_ACCEPTED"


def test_onboarding_twice_and_taken_username_are_conflicts(onboard, client):
    acc = onboard()
    again = acc.post("/v1/onboarding", json={"username": "another" + uuid.uuid4().hex[:6], "accept_rights": True})
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_ONBOARDED"
    user_id, email = new_identity()
    taken = client.post("/v1/onboarding", json={"username": acc.username.upper(), "accept_rights": True},
                        headers=bearer(mint(user_id, email)))
    assert taken.status_code == 409 and taken.json()["code"] == "USERNAME_TAKEN"


def test_email_copy_follows_the_verified_token(onboard, app):
    acc = onboard()
    changed = f"changed{uuid.uuid4().hex[:6]}@example.com"
    resp = acc.client.get("/v1/me", headers=bearer(mint(acc.user_id, changed)))
    assert resp.json()["user"]["email"] == changed


def test_no_token_is_unauthenticated(client):
    resp = client.get("/v1/me")
    assert resp.status_code == 401 and resp.json()["code"] == "UNAUTHENTICATED"
    assert resp.json()["request_id"] == resp.headers["X-Request-ID"]


def _bad_tokens(user_id, email):
    now = int(time.time())
    return {
        "expired": mint(user_id, email, iat=now - 7200, exp=now - 3600),
        "wrong audience": mint(user_id, email, aud="other"),
        "wrong issuer": mint(user_id, email, iss="https://evil.supabase.co/auth/v1"),
        "signed by another key": mint(user_id, email, key=OTHER_KEY),
        "anonymous user": mint(user_id, email, is_anonymous=True),
        "service role": mint(user_id, email, role="service_role"),
        "no email": mint(user_id, None),
        "no exp": mint(user_id, email, exp=None),
        "alg none": jwt.encode({"sub": str(user_id), "email": email, "aud": "authenticated", "role": "authenticated",
                                "iss": "https://testproject.supabase.co/auth/v1", "iat": now, "exp": now + 60},
                               None, algorithm="none"),
        "HS256 with a guessable secret": jwt.encode(
            {"sub": str(user_id), "email": email, "aud": "authenticated", "role": "authenticated",
             "iss": "https://testproject.supabase.co/auth/v1", "iat": now, "exp": now + 60},
            "super-secret-jwt-token-with-at-least-32-characters-long", algorithm="HS256"),
        "garbage": "not.a.jwt",
    }


@pytest.mark.parametrize("case", list(_bad_tokens(uuid.uuid4(), "x@example.com")))
def test_invalid_tokens_get_one_generic_answer(onboard, client, case):
    acc = onboard()
    token = _bad_tokens(acc.user_id, acc.email)[case]
    resp = client.get("/v1/me", headers=bearer(token))
    assert resp.status_code == 401
    assert _strip(resp) == _strip(client.get("/v1/me"))  # same as no token at all


def test_token_is_only_accepted_in_the_authorization_header(onboard, client, app):
    from fastapi.testclient import TestClient

    acc = onboard()
    assert client.get("/v1/me", params={"access_token": acc.token}).status_code == 401
    cookie_client = TestClient(app)
    cookie_client.cookies.set("sb-access-token", acc.token)
    assert cookie_client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": acc.token}).status_code == 401  # no scheme


def test_access_tokens_never_reach_the_logs(onboard, caplog):
    caplog.set_level(logging.DEBUG)
    acc = onboard()
    acc.get("/v1/me")
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "request_id=" in log_text
    assert acc.token not in log_text and acc.token.split(".")[2] not in log_text


def test_signing_key_fixture_is_es256():
    # Guards the simulation: the real project publishes ES256 keys (docs/compatibility.md).
    assert jwt.get_unverified_header(mint(uuid.uuid4(), "a@example.com"))["alg"] == "ES256"
    assert SIGNING_KEY.curve.name == "secp256r1"
