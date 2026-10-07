"""Real phone + real Agent code + real HTTP server (opt-in: CLIPFLOW_REAL_DEVICE=1).

The phone part is real (ADB, `getprop` only — read-only). The account side is simulated: a
synthetic local Workspace with a Supabase-shaped test identity, never a real customer account.
"""

from __future__ import annotations

import os
import uuid

import pytest

from agent.adb import Adb, default_runner
from agent.device_registry import discover, register_ready
from agent.server_client import ServerClient

pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_REAL_DEVICE") != "1",
                                reason="real-device test is opt-in (CLIPFLOW_REAL_DEVICE=1, phone on USB)")


def workspace_with_agent(onboard, server_url):
    acc = onboard()
    env = acc.post("/v1/environments", json={"name": "QA", "registered_agent_limit": 1,
                                             "concurrent_session_limit": 1, "device_limit": 1}).json()
    token = acc.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "QA PC"}).json()["token"]
    client = ServerClient(server_url)
    return acc, client, client.authenticate(acc.username, token, str(uuid.uuid4()))


def test_register_the_phone_on_this_pc(onboard, server_url):
    adb = Adb(default_runner())
    phones = [p for p in discover(adb) if p.state == "device"]
    assert phones, "connect an authorized phone over USB"
    phone = phones[0]
    assert phone.hw_serial == adb.shell(phone.adb_serial, "getprop ro.serialno").strip()

    owner, client, session = workspace_with_agent(onboard, server_url)
    first = register_ready(client, session, phones, only=phone.hw_serial)
    again = register_ready(client, session, phones, only=phone.hw_serial)
    assert [r["outcome"] for r in first] == ["REGISTERED"]
    assert [r["outcome"] for r in again] == ["ALREADY_REGISTERED"]

    listed = owner.get("/v1/devices").json()["items"]
    assert [(d["serial"], d["model"], d["readiness"]) for d in listed] == [(phone.hw_serial, phone.model, "ready")]

    # Another Workspace's Agent on the same PC cannot take the phone (T07).
    other, other_client, other_session = workspace_with_agent(onboard, server_url)
    stolen = register_ready(other_client, other_session, phones, only=phone.hw_serial)
    assert [r["outcome"] for r in stolen] == ["DEVICE_OWNERSHIP_CONFLICT"]
    assert other.get("/v1/devices").json()["items"] == []

    # Release it again so the shared test database holds no binding for the real serial.
    owner.post(f"/v1/devices/{listed[0]['id']}/unbind")
    print(f"real phone: model={phone.model} android={phone.android_version} serial={phone.hw_serial[:4]}…")
