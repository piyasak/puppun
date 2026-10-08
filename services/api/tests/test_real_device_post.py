"""Real phone, dry run (opt-in: CLIPFLOW_REAL_DEVICE=1, QA phone on USB, unlocked).

The whole posting path up to Submit on the real QA phone: schedule -> claim -> verified download
or own copy -> push to a hidden staging name -> SHA-256 on the phone -> rename -> Gallery lists it
-> DRY_RUN_DONE -> test file removed. TikTok is never opened and nothing is posted. The account
side is a synthetic local Workspace. A summary goes to var/evidence/p5_real_device_dry_run.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from api_test_shop import FULL_DAY, Shop, items, set_times

from agent.adb import Adb, default_runner
from agent.device_registry import discover
from agent.post_runner import PostRunner
from agent.server_client import ServerClient

pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_REAL_DEVICE") != "1",
                                reason="real-device test is opt-in (CLIPFLOW_REAL_DEVICE=1, phone on USB)")
EVIDENCE = Path(__file__).resolve().parents[3] / "var" / "evidence" / "p5_real_device_dry_run.json"


def test_dry_run_post_on_the_real_phone(onboard, client, real_clip, app, server_url, tmp_path):
    adb = Adb(default_runner())
    phones = [p for p in discover(adb) if p.state == "device" and p.hw_serial]
    assert phones, "connect the authorized QA phone over USB"
    phone = phones[0]

    shop = Shop(onboard(), client, real_clip, devices=0)
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={
        "name": shop.env["name"], "registered_agent_limit": 1, "concurrent_session_limit": 1, "device_limit": 1})
    dev = shop.w.post("/v1/agent/devices/register", json={"serial": phone.hw_serial, "adb_state": "device",
                                                          "model": phone.model, "android_version": phone.android_version}).json()
    shop.acc.patch(f"/v1/devices/{dev['id']}", json={"display_name": "QA POCO", "expected_account": "qa_dry_run"})
    shop.devices = [dev["id"]]
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id, **FULL_DAY).json()
    set_times(app, series["id"], [-1])

    data_dir = tmp_path / "agent-data"
    srv = ServerClient(server_url)
    session = srv.authenticate(shop.acc.username, shop.token, shop.w.installation_id)
    logs = []
    runner = PostRunner(data_dir, lambda: adb, log=logs.append)
    started = time.perf_counter()
    outcome = runner.run_once(srv, lambda: session)
    elapsed = round(time.perf_counter() - started, 1)

    item = items(shop, series["id"])[0]
    leftovers = adb.shell(phone.adb_serial, "ls /sdcard/Movies/ClipFlow 2>/dev/null").split()
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "phone": {"model": phone.model, "android": phone.android_version},
        "outcome": outcome, "elapsed_s": elapsed, "item_state": item["state"], "log": logs,
        "journal": [json.loads(x) for x in (data_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()],
        "leftover_files": leftovers,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    assert outcome == "DRY_RUN_DONE", logs
    assert item["state"] == "DRY_RUN_DONE" and item["submitted_at"] is None
    assert not any(name.startswith("cf_") for name in leftovers)  # test file removed from the phone
