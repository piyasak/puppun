"""FR-15 / G2-04: phone registration through the Agent, ownership conflicts, caps, unbind (T07)."""

from __future__ import annotations

import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from api_test_agents import Agent
from fastapi.testclient import TestClient

SERIAL = "TST8YD89GI8XCIE6"  # replaced per test: the test database is shared by the whole session


@pytest.fixture(autouse=True)
def _unique_serial(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "SERIAL", f"TST{uuid.uuid4().hex[:12].upper()}")


def make_owner(onboard, client, *, devices=1, env_name="office"):
    acc = onboard()
    acc.env = acc.post("/v1/environments", json={"name": env_name, "registered_agent_limit": 1,
                                                 "concurrent_session_limit": 1, "device_limit": devices}).json()
    token = acc.post("/v1/agent-tokens", json={"environment_id": acc.env["id"], "name": "pc"}).json()["token"]
    acc.agent = Agent(client, acc.username, token)
    assert acc.agent.auth().status_code == 200
    return acc


def register(agent, serial=None, state="device", **kw):
    return agent.post("/v1/agent/devices/register",
                      json={"serial": serial or SERIAL, "adb_state": state, "model": "25078PC3EG", "android_version": "15"} | kw)


@pytest.fixture
def owner(onboard, client):
    return make_owner(onboard, client)


def strip(resp):
    return {k: v for k, v in resp.json().items() if k != "request_id"}


def test_ready_phone_registers_once_and_is_idempotent(owner):
    first = register(owner.agent)
    assert first.status_code == 200 and first.json()["created"] is True
    again = register(owner.agent, SERIAL.lower())  # serials compare case-insensitively
    assert again.json() == first.json() | {"created": False}
    items = owner.get("/v1/devices").json()["items"]
    assert len(items) == 1 and items[0]["serial"] == SERIAL and items[0]["readiness"] == "ready"
    assert owner.get("/v1/workspace/usage").json()["in_use"]["device_limit"] == 1


@pytest.mark.parametrize("state,hint", [("unauthorized", "Allow USB debugging"), ("offline", "ถอดสาย USB")])
def test_phone_that_is_not_ready_is_not_registered(owner, state, hint):
    resp = register(owner.agent, state=state)
    assert resp.status_code == 409 and resp.json()["code"] == "DEVICE_NOT_READY" and hint in resp.json()["message"]
    assert owner.get("/v1/devices").json()["items"] == []


@pytest.mark.parametrize("serial", ["192.168.6.30:5555", "adb-TST8YD89-abc._adb-tls-connect._tcp", "bad serial",
                                    "x", "a" * 65])
def test_unstable_or_invalid_serials_are_rejected(owner, serial):
    assert register(owner.agent, serial).status_code == 422


def test_phone_bound_elsewhere_is_never_moved(owner, onboard, client):  # T07
    assert register(owner.agent).status_code == 200
    other = make_owner(onboard, client)
    stolen = register(other.agent)
    assert stolen.status_code == 409 and stolen.json()["code"] == "DEVICE_OWNERSHIP_CONFLICT"
    assert owner.username not in stolen.text and "office" not in stolen.text
    assert other.get("/v1/devices").json()["items"] == []
    assert owner.get("/v1/devices").json()["items"][0]["unbound_at"] is None


def test_conflict_with_own_other_environment_looks_the_same(onboard, client, owner):
    register(owner.agent)
    env2 = owner.post("/v1/environments", json={"name": "home", "registered_agent_limit": 1,
                                                "concurrent_session_limit": 1, "device_limit": 1}).json()
    token2 = owner.post("/v1/agent-tokens", json={"environment_id": env2["id"], "name": "pc2"}).json()["token"]
    agent2 = Agent(client, owner.username, token2)
    agent2.auth()
    same_ws = register(agent2)
    other = make_owner(onboard, client)
    other_ws = register(other.agent)
    assert same_ws.status_code == other_ws.status_code == 409
    assert strip(same_ws) == strip(other_ws)


def test_device_limit_of_the_environment(owner):
    assert register(owner.agent).status_code == 200
    full = register(owner.agent, f"SECOND{uuid.uuid4().hex[:8]}")
    assert full.status_code == 409 and full.json()["code"] == "DEVICE_LIMIT_REACHED"


def test_unbind_releases_the_serial_for_a_new_owner(owner, onboard, client):
    register(owner.agent)
    device_id = owner.get("/v1/devices").json()["items"][0]["id"]
    unbound = owner.post(f"/v1/devices/{device_id}/unbind").json()
    assert unbound["readiness"] == "unbound" and unbound["unbound_at"]
    assert owner.post(f"/v1/devices/{device_id}/unbind").json()["unbound_at"] == unbound["unbound_at"]
    new_owner = make_owner(onboard, client)
    assert register(new_owner.agent).json()["created"] is True
    assert register(owner.agent).status_code == 409  # now it belongs to the new owner


def test_simultaneous_registration_by_two_workspaces(onboard, client, app):
    a, b = make_owner(onboard, client), make_owner(onboard, client)
    serial = f"RACE{uuid.uuid4().hex[:10]}"

    def go(acc):
        with TestClient(app) as c:
            return c.post("/v1/agent/devices/register", headers={"Authorization": f"Bearer {acc.agent.session}"},
                          json={"serial": serial, "adb_state": "device"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(go, [a, b]))
    assert codes == [200, 409]


def test_reported_states_drive_readiness(owner):
    register(owner.agent)
    owner.agent.post("/v1/agent/devices/report", json={"devices": {SERIAL: "unauthorized"}})
    assert owner.get("/v1/devices").json()["items"][0]["readiness"] == "unauthorized"
    owner.agent.post("/v1/agent/devices/report", json={"devices": {}})
    assert owner.get("/v1/devices").json()["items"][0]["readiness"] == "missing"
    owner.agent.post("/v1/agent/devices/report", json={"devices": {SERIAL.lower(): "device"}})
    assert owner.get("/v1/devices").json()["items"][0]["readiness"] == "ready"
    owner.agent.post("/v1/agent/session/end")
    assert owner.get("/v1/devices").json()["items"][0]["readiness"] == "agent_offline"


def test_report_ignores_phones_bound_elsewhere(owner, onboard, client):
    register(owner.agent)
    other = make_owner(onboard, client)
    assert other.agent.post("/v1/agent/devices/report", json={"devices": {SERIAL: "offline"}}).json() == {"updated": 0}
    assert owner.get("/v1/devices").json()["items"][0]["readiness"] == "ready"


def test_expected_account_and_name_are_editable(owner):
    register(owner.agent)
    device_id = owner.get("/v1/devices").json()["items"][0]["id"]
    body = owner.patch(f"/v1/devices/{device_id}", json={"display_name": "POCO หน้าร้าน",
                                                         "expected_account": "@Patsy4404"}).json()
    assert body["display_name"] == "POCO หน้าร้าน" and body["expected_account"] == "patsy4404"
    assert owner.patch(f"/v1/devices/{device_id}", json={"expected_account": "no spaces allowed"}).status_code == 422
    cleared = owner.patch(f"/v1/devices/{device_id}", json={"expected_account": ""}).json()
    assert cleared["expected_account"] is None and cleared["display_name"] == "POCO หน้าร้าน"


def test_devices_are_tenant_scoped(owner, onboard, client):
    register(owner.agent)
    device_id = owner.get("/v1/devices").json()["items"][0]["id"]
    other = onboard()
    assert other.get("/v1/devices").json()["items"] == []
    assert other.patch(f"/v1/devices/{device_id}", json={"display_name": "x"}).status_code == 404
    assert other.post(f"/v1/devices/{device_id}/unbind").status_code == 404
    assert owner.get("/v1/devices").json()["items"][0]["unbound_at"] is None


def test_device_limit_cannot_drop_below_bound_phones(owner):
    register(owner.agent)
    resp = owner.patch(f"/v1/environments/{owner.env['id']}", json={"device_limit": 0})
    assert resp.status_code == 409 and resp.json()["code"] == "LIMIT_BELOW_USAGE"


def test_web_and_agent_credentials_do_not_cross(owner, client):
    resp = client.post("/v1/agent/devices/register", headers=owner.headers(),
                       json={"serial": SERIAL, "adb_state": "device"})
    assert resp.status_code == 401
    assert client.get("/v1/devices", headers={"Authorization": f"Bearer {owner.agent.session}"}).status_code == 401


def test_register_answer_says_what_details_are_missing_and_where(owner):
    first = register(owner.agent).json()
    assert first["missing_details"] == ["display_name", "expected_account"]
    assert first["details_url"] == f"http://localhost:5173/devices?edit={first['id']}"
    owner.patch(f"/v1/devices/{first['id']}", json={"display_name": "POCO", "expected_account": "@shop1"})
    again = register(owner.agent).json()
    assert again["created"] is False and again["missing_details"] == []
    assert again["expected_account"] == "shop1"
    assert owner.get("/v1/devices").json()["items"][0]["missing_details"] == []
