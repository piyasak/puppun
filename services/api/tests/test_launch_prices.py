"""Launch prices (PO 2026-10-10, D05): free 5-day trial (1 PC, 1 phone, 30 clips) and Starter 200 /
Pro 400 / Business 888 THB a month (1 PC; 5 / 10 / 20 phones; 1,000 / 2,000 / unlimited clips)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from api_test_tokens import SIGNING_KEY, SUPABASE_URL, mint, new_identity
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipflow_api import quota
from clipflow_api.app import create_app
from clipflow_api.config import Settings
from clipflow_api.models import Plan, Subscription


@pytest.fixture
def launch_client(migrated_url, storage):
    """An app as production runs it: new Workspaces get the latest trial (no test pin)."""
    settings = Settings(app_env="test", database_url=migrated_url, supabase_url=SUPABASE_URL,
                        agent_auth_rate_per_minute=10_000, default_plan_version=None)
    app = create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage)
    return TestClient(app), app


def onboard_on(client):
    uid, email = new_identity()
    headers = {"Authorization": f"Bearer {mint(uid, email)}"}
    resp = client.post("/v1/onboarding", json={"username": f"u{uuid.uuid4().hex[:10]}", "accept_rights": True},
                       headers=headers)
    assert resp.status_code == 201, resp.text
    return headers


def test_new_workspaces_get_the_free_5_day_trial(launch_client):
    client, _ = launch_client
    headers = onboard_on(client)
    sub = client.get("/v1/billing/subscription", headers=headers).json()
    assert (sub["status"], sub["plan"]["code"], sub["plan"]["price_satang"]) == ("trial", "trial", 0)
    assert sub["plan"]["limits"] == {"registered_agents": 1, "concurrent_sessions": 1, "devices": 1, "clips_per_cycle": 30}
    days = (datetime.fromisoformat(sub["cycle_end"]) - datetime.fromisoformat(sub["cycle_start"])).days
    assert days == 5 and sub["quota"]["limit"] == 30 and not sub["quota"]["unlimited"]
    # The plan list tells the landing page what the trial is
    assert client.get("/v1/billing/plans").json()["trial"] == {
        "days": 5, "clips": 30, "devices": 1, "registered_agents": 1, "price_satang": 0}
    # 1 PC and 1 phone: a second PC does not fit
    env = client.post("/v1/environments", json={"name": "office", "registered_agent_limit": 2},
                      headers=headers)
    assert env.status_code == 409 and env.json()["code"] == "PLAN_LIMIT_EXCEEDED"


def test_unlimited_clips_reserve_without_a_cap_and_still_count(launch_client):
    client, app = launch_client
    headers = onboard_on(client)
    with app.state.db.sessionmaker() as s:
        business = s.scalars(select(Plan).where(Plan.code == "business").order_by(Plan.version.desc())).first()
        assert business.clips_per_month is None and business.price_satang == 88800 and business.max_devices == 20
        sub = s.scalars(select(Subscription).join(Plan, Plan.id == Subscription.plan_id)
                        .where(Plan.code == "trial").order_by(Subscription.created_at.desc())).first()
        sub.plan_id, sub.status = business.id, "active"
        workspace = sub.workspace_id
        s.commit()
    with app.state.db.sessionmaker() as s:
        at = datetime.now(UTC)
        quota.reserve(s, workspace, None, 5000, at)  # far beyond any capped plan
        s.commit()
        summary = quota.summary(s, workspace, at)
    assert summary["unlimited"] and summary["limit"] is None and summary["available"] is None
    usage = client.get("/v1/workspace/usage", headers=headers).json()["clips"]
    assert usage["unlimited"] and usage["used"] == 5000  # still counted (reports, fair billing later)


def test_admin_sets_prices_and_opens_or_closes_a_plan(onboard, app, client):
    """PO 2026-10-10: admins change prices themselves and switch selling / the Demo label."""
    from test_admin import make_staff  # noqa: PLC0415

    admin, customer = onboard(), onboard()
    make_staff(app, admin, "admin")
    reason = "ปรับราคาตามที่ PO ตั้ง (ทดสอบ)"
    try:
        made = admin.post("/v1/admin/plans/starter/versions",
                          json={"price_satang": 25000, "max_devices": 6, "unlimited_clips": True, "interval_days": 30,
                                "reason": reason})
        assert made.status_code == 200, made.text
        offered = {p["code"]: p for p in customer.get("/v1/billing/plans").json()["items"]}
        assert offered["starter"]["price_satang"] == 25000 and offered["starter"]["limits"]["clips_per_cycle"] is None

        closed = admin.post("/v1/admin/plans/starter/status", json={"selling": False, "reason": reason}).json()
        assert closed["selling"] is False
        assert "starter" not in {p["code"] for p in customer.get("/v1/billing/plans").json()["items"]}
        assert customer.post("/v1/billing/checkout", json={"plan_code": "starter", "idempotency_key": uuid.uuid4().hex}
                             ).status_code in (404, 409, 422)
        demo = admin.post("/v1/admin/plans/starter/status", json={"selling": True, "demo": True, "reason": reason}).json()
        assert demo == {"code": "starter", "version": made.json()["version"], "selling": True, "demo": True}
        assert {p["code"]: p for p in customer.get("/v1/billing/plans").json()["items"]}["starter"]["example_price"]
        assert admin.post("/v1/admin/plans/trial/status", json={"selling": True, "reason": reason}).status_code == 422
        assert customer.post("/v1/admin/plans/starter/status", json={"selling": False, "reason": reason}).status_code == 404  # staff-only routes are hidden
    finally:  # put the launch Starter back for the rest of the session's tests
        admin.post("/v1/admin/plans/starter/versions", json={"price_satang": 20000, "max_devices": 5, "clips_per_month": 1000,
                                                              "is_demo": False, "reason": reason})
