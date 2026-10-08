"""Opt-in (G3-01): a real linked source through the whole job flow, with the Agent job runner.

    CLIPFLOW_REAL_SOURCE_URL=https://www.youtube.com/watch?v=... pytest services/api/tests/test_real_source_job.py

Use only sources the workspace owner has declared rights to (P1 test corpus). Needs the network;
a bot check ends as SOURCE_RATE_LIMITED with a cool-down, never a proxy or IP change. A summary
(no local paths) is written to var/evidence/p33_real_source.json.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import pytest

from agent.job_runner import JobRunner
from agent.server_client import ServerClient

URL = os.environ.get("CLIPFLOW_REAL_SOURCE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set CLIPFLOW_REAL_SOURCE_URL to run against a real source")
EVIDENCE = Path(__file__).resolve().parents[3] / "var" / "evidence" / "p33_real_source.json"


def test_real_source_job_delivers_checked_clips(onboard, server_url, tmp_path):
    owner = onboard()
    env = owner.post("/v1/environments", json={"name": "office", "registered_agent_limit": 1,
                                               "concurrent_session_limit": 1, "device_limit": 0}).json()
    token = owner.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    job_id = owner.post("/v1/jobs", json={"idempotency_key": uuid.uuid4().hex, "environment_id": env["id"],
                                          "source": {"kind": "url", "url": URL}, "requested_clips": 2}).json()["id"]
    client = ServerClient(server_url)
    session = client.authenticate(owner.username, token, str(uuid.uuid4()))
    logs = []
    runner = JobRunner(tmp_path / "agent-data", log=logs.append)
    # As in `agent.cli connect`: heartbeats on their own thread keep the session alive while the job runs.
    done = threading.Event()

    def heartbeat():
        while not done.wait(session.heartbeat_interval_s):
            client.heartbeat(session)

    threading.Thread(target=heartbeat, daemon=True).start()
    started = time.perf_counter()
    try:
        outcome = runner.run_once(client, lambda: session)
    finally:
        done.set()
    elapsed = round(time.perf_counter() - started, 1)

    job = owner.get(f"/v1/jobs/{job_id}").json()
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "source": URL, "outcome": outcome, "elapsed_s": elapsed, "log": logs,
        "job": {k: job[k] for k in ("state", "planned_clips", "seed", "source_duration_s", "notice", "error",
                                    "quota", "clip_min_s", "clip_max_s")},
        "clips": [{k: c[k] for k in ("index", "start_ms", "end_ms", "duration_ms", "render_sha256", "size_bytes",
                                     "check_status", "checks", "title", "metadata", "template_version")}
                  for c in job["clips"]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    assert outcome == "READY_FOR_REVIEW", job["error"]
    assert job["planned_clips"] == 2 and len(job["clips"]) == 2
    assert all(c["check_status"] == "passed" for c in job["clips"]), [c["checks"] for c in job["clips"]]
    assert job["quota"] == {"reserved": 2, "settled": 2, "released": 0, "outstanding": 0}
