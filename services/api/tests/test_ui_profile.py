"""Q-50: the TikTok UI profile is edited by an admin (versioned, reason, audited) and read by Agents."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from clipflow_api import manage
from clipflow_api.models import AuditEvent

REASON = "TikTok 41 เปลี่ยนชื่อแท็บโปรไฟล์"


@pytest.fixture
def admin(onboard, app):
    acc = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, acc.email, "admin") == 0
    return acc


def agent_get(shop, client, path):
    return client.get(path, headers={"Authorization": f"Bearer {shop.w.session}"})


def test_agents_use_their_built_in_profile_until_an_admin_saves_one(shop, admin, app, client):
    assert agent_get(shop, client, "/v1/agent/ui-profile").status_code == 404
    shown = admin.get("/v1/admin/ui-profile").json()
    assert shown["current"] is None and shown["defaults"]["profile_tab"] == ["โปรไฟล์", "Profile"]
    saved = admin.post("/v1/admin/ui-profile", json={"body": {"profile_tab": ["Profil"]}, "reason": REASON})
    assert saved.status_code == 201 and saved.json()["version"] == 1
    assert agent_get(shop, client, "/v1/agent/ui-profile").json() == {"version": 1, "body": {"profile_tab": ["Profil"]}}
    again = admin.post("/v1/admin/ui-profile", json={"body": {"verify_tries": 6}, "reason": REASON})
    assert again.json()["version"] == 2
    assert agent_get(shop, client, "/v1/agent/ui-profile").json()["version"] == 2
    assert [h["version"] for h in admin.get("/v1/admin/ui-profile").json()["history"]] == [2, 1]
    with app.state.db.sessionmaker() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.action == "admin.ui_profile.save")).all()
        assert len(rows) == 2 and all(r.reason == REASON for r in rows)


def test_only_an_admin_saves_and_only_a_valid_profile(admin, onboard, app):
    support = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, support.email, "support") == 0
    assert support.get("/v1/admin/ui-profile").status_code == 200  # support reads
    assert support.post("/v1/admin/ui-profile", json={"body": {}, "reason": REASON}).status_code == 403
    assert onboard().post("/v1/admin/ui-profile", json={"body": {}, "reason": REASON}).status_code == 404
    bad = admin.post("/v1/admin/ui-profile", json={"body": {"post_button": ["x"], "settle_s": 0}, "reason": REASON})
    assert bad.status_code == 422 and bad.json()["code"] == "UI_PROFILE_INVALID"
    assert "post_button" in bad.json()["details"]["problems"] and "settle_s" in bad.json()["details"]["problems"]
    assert admin.post("/v1/admin/ui-profile", json={"body": {}, "reason": "short"}).status_code == 422
