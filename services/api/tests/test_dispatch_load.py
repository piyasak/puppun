"""Opt-in load test for G4-05: 95% of due posts are handed to an Agent within 60 s of their slot.

    CLIPFLOW_LOAD=1 .venv/Scripts/python -m pytest services/api/tests/test_dispatch_load.py -s

50 Workspaces (the NF-04 target size) on the demo plan, each with one Agent and three phones:
150 phones, 300 posts falling due over ~2 minutes. Every Agent is a thread speaking real HTTP to
the API (uvicorn), polling claim every POLL_S while idle and finishing each post as a dry run.
Clips are written straight into the throwaway database (rendering is not what is measured here);
series are created through the API so they pass the same validation as real ones. Latency is
claimed_at - scheduled_at from the database. A summary is written to var/evidence/p45_dispatch_load.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import statistics
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, update

from clipflow_api.models import Clip, ClipMetadata, Job, ScheduleItem

pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_LOAD") != "1", reason="load test is opt-in (CLIPFLOW_LOAD=1)")

WORKSPACES, PHONES, POSTS_PER_PHONE = 50, 3, 2
POLL_S = 15.0  # idle poll interval of the Agent (E-41)
SPREAD_S = 120  # due times spread over this window
POST_S = 1.0  # simulated time a dry-run post occupies the phone
EVIDENCE = Path(__file__).resolve().parents[3] / "var" / "evidence" / "p45_dispatch_load.json"


def seed_clips(app, job_id: str, count: int) -> None:
    """Delivered, checked and approved clips for an existing job (straight into the database)."""
    with app.state.db.sessionmaker() as s:
        job = s.get(Job, uuid.UUID(job_id))
        for i in range(1, count + 1):
            sha = hashlib.sha256(f"{job_id}-{i}".encode()).hexdigest()
            clip = Clip(workspace_id=job.workspace_id, job_id=job.id, clip_index=i, start_ms=i * 300_000,
                        end_ms=i * 300_000 + 200_000, seed=job.seed, template_version="tpl-default-v2",
                        render_sha256=sha, size_bytes=1000, duration_ms=200_000, title=f"คลิป {i}",
                        storage_key=f"load/{job_id}/{i}.mp4", uploaded_at=datetime.now(UTC), check_status="passed",
                        check_results={"status": "passed", "checks": []}, metadata_version=1,
                        approved_metadata_version=1, approved_sha256=sha, approved_at=datetime.now(UTC),
                        approval_mode="manual")
            s.add(clip)
            s.flush()
            s.add(ClipMetadata(workspace_id=job.workspace_id, clip_id=clip.id, version=1, caption=f"ตอนที่ {i}",
                               hashtags=["#คลิปสั้น"]))
        job.state, job.planned_clips = "READY_FOR_REVIEW", count
        s.commit()


def setup_workspace(onboard, server_url, app, n: int) -> dict:
    acc = onboard()
    env = acc.post("/v1/environments", json={"name": f"load-{n}", "registered_agent_limit": 1,
                                             "concurrent_session_limit": 1, "device_limit": PHONES}).json()
    token = acc.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    installation_id = str(uuid.uuid4())
    signed_in = sign_in(server_url, acc.username, token, installation_id)
    session = signed_in["session_token"]
    auth = {"Authorization": f"Bearer {session}"}
    serials = []
    for p in range(PHONES):
        serial = f"LD{n:02d}{p}{uuid.uuid4().hex[:8].upper()}"
        dev = httpx.post(f"{server_url}/v1/agent/devices/register", headers=auth, json={
            "serial": serial, "adb_state": "device", "model": "25078PC3EG", "android_version": "15"}).json()
        acc.patch(f"/v1/devices/{dev['id']}", json={"display_name": f"P{p}", "expected_account": f"shop{n}x{p}"})
        serials.append((serial, dev["id"]))
    series_ids = []
    for _serial, device_id in serials:
        job_id = acc.post("/v1/jobs", json={
            "idempotency_key": uuid.uuid4().hex, "environment_id": env["id"], "requested_clips": POSTS_PER_PHONE,
            "source": {"kind": "url", "url": "https://www.youtube.com/watch?v=PBES5k67dhI"}}).json()["id"]
        seed_clips(app, job_id, POSTS_PER_PHONE)
        start = (datetime.now(UTC) + timedelta(days=1)).astimezone().strftime("%Y-%m-%dT%H:00")
        resp = acc.post("/v1/schedules", json={
            "idempotency_key": uuid.uuid4().hex, "job_id": job_id, "device_id": device_id, "start_local": start,
            "interval_hours": 1, "window_start": "00:00", "window_end": "24:00"})
        assert resp.status_code == 201, resp.text
        series_ids.append(resp.json()["id"])
    return {"username": acc.username, "token": token, "installation_id": installation_id,
            "serials": [s for s, _ in serials], "series": series_ids}


def sign_in(server_url, username, token, installation_id) -> dict:
    return httpx.post(f"{server_url}/v1/agent/authenticate", json={
        "username": username, "token": token, "installation_id": installation_id, "agent_version": "0.1.0",
    }, timeout=30).json()


def agent_loop(server_url: str, shop: dict, stop: threading.Event, stats: dict, lock: threading.Lock) -> None:
    stop.wait(random.uniform(0, POLL_S))  # Agents start at different moments, as real PCs do
    # Like `agent.cli connect`: sign in when the Agent starts (setup took minutes; earlier sessions expired).
    signed_in = sign_in(server_url, shop["username"], shop["token"], shop["installation_id"])
    auth = {"Authorization": f"Bearer {signed_in['session_token']}"}
    generation = signed_in["generation"]
    with httpx.Client(base_url=server_url, headers=auth, timeout=30) as http:
        while not stop.is_set():
            got = False
            for _ in range(len(shop["serials"])):  # a free phone may take the next post right away
                t0 = time.perf_counter()
                resp = http.post("/v1/agent/posts/claim", json={"ready_serials": shop["serials"]})
                with lock:
                    stats["claim_ms"].append((time.perf_counter() - t0) * 1000)
                    if resp.status_code != 200:
                        stats["errors"].append(f"claim {resp.status_code} {resp.text[:80]}")
                post = resp.json().get("post") if resp.status_code == 200 else None
                if not post:
                    break
                got = True
                for kind in ("TRANSFERRING", "PREPARING", "DRY_RUN_DONE"):
                    if kind == "DRY_RUN_DONE":
                        time.sleep(POST_S)
                    r = http.post(f"/v1/agent/posts/{post['id']}/events",
                                  json={"event_id": uuid.uuid4().hex, "type": kind})
                    if r.status_code != 200:
                        with lock:
                            stats["errors"].append(f"{kind} {r.status_code} {r.text[:80]}")
            if not got:
                stop.wait(POLL_S)
            # heartbeat keeps the session alive (TTL 90 s)
            hb = http.post("/v1/agent/heartbeat", json={"generation": generation})
            if hb.status_code != 200:
                with lock:
                    stats["errors"].append(f"heartbeat {hb.status_code} {hb.text[:80]}")


def test_dispatch_latency_under_load(onboard, server_url, app):
    shops = [setup_workspace(onboard, server_url, app, n) for n in range(WORKSPACES)]
    # Spread the due times: every phone gets two posts, POST_S apart at least, inside SPREAD_S.
    t0 = datetime.now(UTC) + timedelta(seconds=20)
    with app.state.db.sessionmaker() as s:
        all_items = s.scalars(select(ScheduleItem).where(ScheduleItem.series_id.in_(
            [uuid.UUID(x) for shop in shops for x in shop["series"]])).order_by(ScheduleItem.id)).all()
        for k, item in enumerate(all_items):
            s.execute(update(ScheduleItem).where(ScheduleItem.id == item.id).values(
                scheduled_at=t0 + timedelta(seconds=(k * SPREAD_S) / len(all_items))))
        s.commit()
    total = len(all_items)

    stop, lock = threading.Event(), threading.Lock()
    stats = {"claim_ms": [], "errors": []}
    threads = [threading.Thread(target=agent_loop, args=(server_url, shop, stop, stats, lock), daemon=True)
               for shop in shops]
    started = time.perf_counter()
    for t in threads:
        t.start()
    deadline = time.time() + 20 + SPREAD_S + 120
    with app.state.db.sessionmaker() as s:
        while time.time() < deadline:
            done = s.scalar(select(ScheduleItem.id).where(ScheduleItem.id.in_([i.id for i in all_items]),
                                                          ScheduleItem.state != "DRY_RUN_DONE").limit(1))
            if done is None:
                break
            time.sleep(2)
            s.expire_all()
    stop.set()
    for t in threads:
        t.join(timeout=POLL_S + 30)

    with app.state.db.sessionmaker() as s:
        rows = s.execute(select(ScheduleItem.state, ScheduleItem.scheduled_at, ScheduleItem.claimed_at).where(
            ScheduleItem.id.in_([i.id for i in all_items]))).all()
    latencies = sorted((c - sch).total_seconds() for _, sch, c in rows if c is not None)
    p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else None
    within = sum(1 for x in latencies if x <= 60)
    claim_ms = sorted(stats["claim_ms"])
    summary = {
        "date": datetime.now(UTC).isoformat(), "workspaces": WORKSPACES, "phones": WORKSPACES * PHONES,
        "posts": total, "poll_s": POLL_S, "spread_s": SPREAD_S, "elapsed_s": round(time.perf_counter() - started, 1),
        "states": {st: sum(1 for r in rows if r[0] == st) for st in {r[0] for r in rows}},
        "dispatched": len(latencies), "within_60s": within,
        "within_60s_pct": round(100 * within / total, 2),
        "latency_s": {"p50": round(statistics.median(latencies), 2) if latencies else None,
                      "p95": round(p95, 2) if p95 is not None else None,
                      "max": round(latencies[-1], 2) if latencies else None,
                      "min": round(latencies[0], 2) if latencies else None},
        "claim_request_ms": {"p50": round(statistics.median(claim_ms), 1),
                             "p95": round(claim_ms[int(0.95 * (len(claim_ms) - 1))], 1), "count": len(claim_ms)},
        "http_errors": len(stats["errors"]), "error_samples": sorted(set(stats["errors"]))[:10],
        "early": sum(1 for x in latencies if x < 0),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    assert summary["early"] == 0  # nothing before its slot
    assert summary["http_errors"] == 0
    assert summary["dispatched"] == total
    assert summary["within_60s_pct"] >= 95.0
