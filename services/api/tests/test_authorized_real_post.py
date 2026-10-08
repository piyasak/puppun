"""One authorized real post (a recorded PO grant: one post, QA phone, @patsy4404, "only you"), G5-04 + G5-05.

    CLIPFLOW_AUTHORIZED_POST=Q-30 .venv/Scripts/python -m pytest services/api/tests/test_authorized_real_post.py -s

Real phone, real TikTok, real Agent code; the server is the local live-mode test app with a throwaway
database. The flow: schedule -> claim -> push + hash + Gallery -> account check -> share -> only you ->
Thai caption with the attempt marker -> grant used (recorded) -> server re-checks -> Post pressed once
-> the Agent "dies" right there (fault injection) -> the server turns the post UNKNOWN and never hands
it out again -> the Agent's verification finds exactly one new private video carrying the marker ->
a person-style resolution with that evidence -> VERIFIED_SUCCESS.

The grant ledger is var/agent/authorizations.json (kept across runs): a second run is refused before
anything is pressed. A summary without screenshots goes to var/evidence/p5_authorized_post.json.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
from api_test_shop import FULL_DAY, Shop, expire, items, set_times

from agent import authorization
from agent.adb import Adb, default_runner
from agent.attempt import AttemptJournal
from agent.device_registry import discover
from agent.post_runner import PostRunner
from agent.server_client import ServerClient
from agent.tiktok_ui import TikTokUi, UiStop

ROOT = Path(__file__).resolve().parents[3]
# The PO decision that grants the post (Q-29 was used without a post; Q-30 replaces it). It must be
# recorded and accepted in docs/decisions.md; each decision allows exactly one post (ledger).
DECISION = os.environ.get("CLIPFLOW_AUTHORIZED_POST", "")


def _recorded(decision: str) -> bool:
    text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
    row = next((line for line in text.splitlines() if line.startswith(f"| {decision} |")), "")
    return bool(decision) and "Accepted" in row and "1 โพสต์" in row


pytestmark = pytest.mark.skipif(not _recorded(DECISION),
                                reason="runs only with CLIPFLOW_AUTHORIZED_POST=<accepted one-post PO decision>")
LEDGER = ROOT / "var" / "agent" / "authorizations.json"
EVIDENCE = ROOT / "var" / "evidence" / "p5_authorized_post.json"
ACCOUNT = "patsy4404"


def test_the_one_authorized_post(onboard, client, real_clip, app, server_url, live_server_url, tmp_path):
    adb = Adb(default_runner())
    phones = [p for p in discover(adb) if p.state == "device" and p.hw_serial]
    assert phones, "connect the QA phone over USB, unlocked"
    phone = phones[0]
    ui = TikTokUi(adb, phone.adb_serial)

    shop = Shop(onboard(), client, real_clip, devices=0)
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={
        "name": shop.env["name"], "registered_agent_limit": 2, "concurrent_session_limit": 2, "device_limit": 1})
    dev = shop.w.post("/v1/agent/devices/register", json={"serial": phone.hw_serial, "adb_state": "device",
                                                          "model": phone.model, "android_version": phone.android_version}).json()
    shop.acc.patch(f"/v1/devices/{dev['id']}", json={"display_name": "QA POCO", "expected_account": ACCOUNT})
    shop.devices = [dev["id"]]
    job_id, clip_ids = shop.job(clips=1, approve=0)
    shop.acc.patch(f"/v1/clips/{clip_ids[0]}/metadata", json={
        "expected_version": 1, "caption": f"ทดสอบระบบ punpun ({DECISION}) ห้ามเผยแพร่", "hashtags": ["#ทดสอบ", "#punpun"]})
    shop.acc.post(f"/v1/clips/{clip_ids[0]}/approve", json={"metadata_version": 2})
    series = shop.create(job_id, **FULL_DAY).json()
    set_times(app, series["id"], [-1])
    item_id = series["items"][0]["id"]
    marker = "cf" + item_id.replace("-", "")[:6]

    try:
        ui.account()
        before = ui.private_count()
    finally:
        ui.close()

    data_dir = tmp_path / "agent-data"
    posting = ServerClient(live_server_url)
    session = posting.authenticate(shop.acc.username, shop.token, str(uuid.uuid4()))
    runner = PostRunner(data_dir, lambda: adb, log=print, ui_factory=lambda a, s: ui, crash_after_submit=True,
                        grant_source=lambda note: authorization.take(LEDGER, DECISION, 1, note))
    # As in `agent.cli connect`: heartbeats on their own thread keep the session alive during the TikTok steps.
    beating = threading.Event()

    def heartbeat():
        while not beating.wait(15):
            posting.heartbeat(session)

    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        outcome = runner.run_once(posting, lambda: session)
    finally:
        beating.set()  # the "crash": the Agent stops beating too
    summary = {"decision": DECISION, "account": ACCOUNT, "marker": marker, "private_before": before,
               "outcome": outcome}
    try:
        assert outcome == "crashed", f"expected the simulated crash right after Post, got {outcome}"
        assert items(shop, series["id"])[0]["state"] == "SUBMITTING"

        # The Agent is gone: the lease runs out, the post becomes UNKNOWN, and nothing is handed out again.
        expire(app, item_id)
        assert posting.claim_post(session, [phone.hw_serial]) is None
        unknown = items(shop, series["id"])[0]
        assert unknown["state"] == "UNKNOWN"
        attempt = f"{item_id}-1"
        assert AttemptJournal(data_dir / "attempts.jsonl").recover(attempt).value == "UNKNOWN"

        # Reconcile with evidence from the phone (upload may take a little while).
        evidence = None
        for _ in range(6):
            time.sleep(20)
            try:
                evidence = ui.verify_private_post(marker, before)
                break
            except UiStop as exc:
                summary.setdefault("verify_tries", []).append(exc.code)
            finally:
                ui.close()
        assert evidence is not None, summary
        resolved = shop.acc.post(f"/v1/schedule-items/{item_id}/resolve", json={
            "decision": "found_published", "evidence": json.dumps(evidence, ensure_ascii=False),
            "expected_state_version": unknown["state_version"]})
        assert resolved.status_code == 200 and resolved.json()["state"] == "VERIFIED_SUCCESS"
        summary.update(evidence=evidence, final_state="VERIFIED_SUCCESS")

        with pytest.raises(authorization.GrantRefused):  # the one post is used
            authorization.take(LEDGER, DECISION, 1, "second attempt")
    finally:
        remote = f"/sdcard/Movies/ClipFlow/cf_{item_id[:8]}_01.mp4"
        adb.shell(phone.adb_serial, f"rm -f '{remote}' /sdcard/cf_ui.xml")
        adb.shell(phone.adb_serial, f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{remote}'")
        summary["ime"] = adb.shell(phone.adb_serial, "settings get secure default_input_method").strip()
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
