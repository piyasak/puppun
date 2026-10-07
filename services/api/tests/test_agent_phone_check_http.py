"""Q-25 over real HTTP: the Agent's start-up phone check registers phones and points to the web.

ADB is simulated here (the real phone is covered by test_real_device_registration, opt-in).
"""

from __future__ import annotations

import uuid

from agent.adb import Adb
from agent.device_registry import DeviceSync
from agent.server_client import ServerClient, run_connection


def fake_adb(serial: str):
    props = {"ro.serialno": serial, "ro.product.model": "25078PC3EG", "ro.build.version.release": "15"}

    def runner(args):
        if args[:2] == ["devices", "-l"]:
            return f"List of devices attached\n{serial}  device model:25078PC3EG transport_id:1\n"
        return props[args[3].split()[1]] + "\n"

    return Adb(runner)


def test_agent_start_registers_new_phone_and_tells_where_to_finish(server_url, onboard):
    owner = onboard()
    env = owner.post("/v1/environments", json={"name": "หน้าร้าน", "device_limit": 1}).json()
    token = owner.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    serial = f"QA{uuid.uuid4().hex[:10].upper()}"
    installation_id = str(uuid.uuid4())  # kept on disk by the real Agent, same after a restart
    logs = []
    sync = DeviceSync(lambda: fake_adb(serial), log=logs.append)

    result = run_connection(ServerClient(server_url), owner.username, token, installation_id, duration_s=0,
                            log=logs.append, on_session=sync)
    assert result.stopped_because == "duration_elapsed"
    device = owner.get("/v1/devices").json()["items"][0]
    assert device["serial"] == serial and device["missing_details"] == ["display_name", "expected_account"]
    assert f"ลงทะเบียนโทรศัพท์ 25078PC3EG ({serial}) แล้ว" in logs[1]
    assert f"/devices?edit={device['id']}" in logs[1]

    # Restart after the owner filled in the details: no new registration, "ready" message.
    owner.patch(f"/v1/devices/{device['id']}", json={"display_name": "POCO หน้าร้าน", "expected_account": "shop1"})
    logs.clear()
    run_connection(ServerClient(server_url), owner.username, token, installation_id, duration_s=0,
                   log=logs.append, on_session=DeviceSync(lambda: fake_adb(serial), log=logs.append))
    assert logs[1] == f"โทรศัพท์ POCO หน้าร้าน ({serial}) พร้อมใช้งาน (บัญชี TikTok @shop1)"
    assert len(owner.get("/v1/devices").json()["items"]) == 1
