"""Phone screen diagnostics (PO 2026-10-16): the Agent uploads, the Workspace and staff look, kept 7 days."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from clipflow_api import diagnostics as rules
from clipflow_api import manage
from clipflow_api.models import AuditEvent, Diagnostic

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
XML = b"<hierarchy><node text=\"@jk.mickey\" /></hierarchy>"


def agent(shop, client, method, path, **kw):
    headers = {"Authorization": f"Bearer {shop.w.session}"} | kw.pop("headers", {})
    return client.request(method, path, headers=headers, **kw)


def device_id(shop):
    return shop.acc.get("/v1/devices").json()["items"][0]["id"]


def test_a_check_asked_on_the_web_is_run_by_the_agent_and_shown_to_the_workspace_only(shop, client, onboard, app):
    dev = device_id(shop)
    asked = shop.acc.post(f"/v1/devices/{dev}/diagnostics", json={"check": "newest_public_video"})
    assert asked.status_code == 201 and asked.json()["status"] == "requested"
    assert shop.acc.post(f"/v1/devices/{dev}/diagnostics", json={"check": "profile"}).json()["code"] == "DIAGNOSTIC_OPEN"
    assert shop.acc.post(f"/v1/devices/{dev}/diagnostics", json={"check": "post_something"}).status_code == 422
    other = onboard()
    assert other.post(f"/v1/devices/{dev}/diagnostics", json={"check": "profile"}).status_code == 404

    got = agent(shop, client, "POST", "/v1/agent/diagnostics/requested", json={"ready_serials": [shop.serial]}).json()
    diag = got["diagnostic"]
    assert diag["check"] == "newest_public_video" and diag["serial"] == shop.serial
    assert agent(shop, client, "POST", "/v1/agent/diagnostics/requested",
                 json={"ready_serials": [shop.serial]}).json()["diagnostic"] is None  # handed out once
    for step, (name, ext, data) in enumerate([("profile", "png", PNG), ("profile", "xml", XML)]):
        r = agent(shop, client, "PUT", f"/v1/agent/diagnostics/{diag['id']}/files/{step // 2}/{name}.{ext}", content=data)
        assert r.status_code == 200, r.text
    bad = agent(shop, client, "PUT", f"/v1/agent/diagnostics/{diag['id']}/files/1/x.png", content=b"not a png")
    assert bad.status_code == 422
    assert agent(shop, client, "POST", f"/v1/agent/diagnostics/{diag['id']}/done", json={"note": "1 screen"}).json() == {"status": "done"}
    assert agent(shop, client, "PUT", f"/v1/agent/diagnostics/{diag['id']}/files/2/late.png", content=PNG).status_code == 409

    listed = shop.acc.get(f"/v1/devices/{dev}/diagnostics").json()["items"]
    assert len(listed) == 1 and "url" not in listed[0]["files"][0]  # no links in the list
    shown = shop.acc.get(f"/v1/diagnostics/{diag['id']}").json()
    assert {f["kind"] for f in shown["files"]} == {"png", "xml"} and all(f["url"] for f in shown["files"])
    assert other.get(f"/v1/diagnostics/{diag['id']}").status_code == 404
    with app.state.db.sessionmaker() as s:
        assert s.scalars(select(AuditEvent).where(AuditEvent.action == "diagnostic.view")).first() is not None


def test_a_failure_capture_is_tied_to_the_post_and_staff_can_see_it(shop, client, onboard, app):
    created = agent(shop, client, "POST", "/v1/agent/diagnostics", json={"serial": shop.serial, "code": "VERIFY_UNREADABLE"})
    assert created.status_code == 201
    diag_id = created.json()["id"]
    assert agent(shop, client, "PUT", f"/v1/agent/diagnostics/{diag_id}/files/0/stopped.png", content=PNG).status_code == 200
    agent(shop, client, "POST", f"/v1/agent/diagnostics/{diag_id}/done", json={"note": "VERIFY_UNREADABLE"})
    support = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, support.email, "support") == 0
    assert any(d["id"] == diag_id for d in support.get("/v1/admin/diagnostics").json()["items"])
    assert support.get(f"/v1/admin/diagnostics/{diag_id}").json()["files"][0]["url"]
    assert shop.acc.get("/v1/admin/diagnostics").status_code == 404  # customers never reach the staff list


def test_captures_are_deleted_after_seven_days(shop, client, app):
    diag_id = agent(shop, client, "POST", "/v1/agent/diagnostics", json={"serial": shop.serial, "code": "X"}).json()["id"]
    agent(shop, client, "PUT", f"/v1/agent/diagnostics/{diag_id}/files/0/stopped.png", content=PNG)
    with app.state.db.sessionmaker() as s:
        row = s.get(Diagnostic, uuid.UUID(diag_id))
        key = row.files[0]["key"]
        assert row.expires_at - row.created_at >= timedelta(days=rules.KEEP_DAYS) - timedelta(minutes=1)
        s.execute(update(Diagnostic).where(Diagnostic.id == row.id).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    assert app.state.storage.exists(key)
    assert shop.acc.get(f"/v1/devices/{device_id(shop)}/diagnostics").json()["items"] == []  # purged on the call
    with app.state.db.sessionmaker() as s:
        assert s.get(Diagnostic, uuid.UUID(diag_id)) is None
    assert not app.state.storage.exists(key)
