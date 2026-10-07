"""P3.1 / G3-04 / FR-21: job lifecycle with the Agent and the quota ledger.

UAT: T09 (short source), T10 (render failure + repeated events), T21 (two jobs, last units).
Demo plan quota: 30 clips per month (migration 0005).
"""

from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from api_test_agents import Agent
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from clipflow_api.models import Job, QuotaLedger

URL = "https://www.youtube.com/watch?v=PBES5k67dhI"


def content(i: int) -> bytes:
    return f"clip-{i}".encode()  # stand-in file; real media is covered in test_clips.py


def sha(i: int) -> str:
    return hashlib.sha256(content(i)).hexdigest()


class Worker(Agent):
    """An Agent that also speaks the job protocol."""

    def claim(self):
        return self.post("/v1/agent/jobs/claim").json()["job"]

    def event(self, job_id, type_, event_id=None, **payload):
        return self.post(f"/v1/agent/jobs/{job_id}/events",
                         json={"event_id": event_id or uuid.uuid4().hex, "type": type_, **payload})

    def clip(self, job_id, index, event_id=None, digest=None, duration_ms=200_000, upload=True):
        """Report a rendered clip and (by default) upload its file, as the real Agent does."""
        resp = self.event(job_id, "clip_rendered", event_id, index=index, start_ms=index * 400_000,
                          end_ms=index * 400_000 + duration_ms, duration_ms=duration_ms, sha256=digest or sha(index),
                          size_bytes=len(content(index)), template_version="tpl-default-v2", title=f"คลิป {index}")
        if upload and resp.status_code == 200:
            self.upload(job_id, index)
        return resp

    def upload(self, job_id, index, body=None):
        return self.client.put(f"/v1/agent/jobs/{job_id}/clips/{index}/file", content=body or content(index),
                               headers={"Authorization": f"Bearer {self.session}", "Content-Type": "video/mp4"})

    def run_to_rendering(self, job_id, possible=5):
        assert self.event(job_id, "source_validated", duration_s=3600, possible_clips=possible).status_code == 200
        for stage in ("DOWNLOADING", "ANALYZING", "RENDERING"):
            assert self.event(job_id, "stage", stage=stage).status_code == 200


@pytest.fixture
def ws(onboard, client):
    acc = onboard()
    acc.env = acc.post("/v1/environments", json={"name": "office", "registered_agent_limit": 2,
                                                 "concurrent_session_limit": 2, "device_limit": 0}).json()
    token = acc.post("/v1/agent-tokens", json={"environment_id": acc.env["id"], "name": "pc"}).json()["token"]
    acc.worker = lambda installation_id=None: _worker(client, acc.username, token, installation_id)
    acc.w = acc.worker()
    acc.new_job = lambda **kw: acc.post("/v1/jobs", json={
        "idempotency_key": uuid.uuid4().hex, "environment_id": acc.env["id"],
        "source": {"kind": "url", "url": URL}} | kw)
    return acc


def _worker(client, username, token, installation_id=None):
    w = Worker(client, username, token, installation_id)
    assert w.auth().status_code == 200
    return w


def ledger(app, job_id):
    with app.state.db.sessionmaker() as s:
        return sorted((r.entry, r.units, r.reason) for r in s.scalars(
            select(QuotaLedger).where(QuotaLedger.job_id == uuid.UUID(job_id))).all())


# --- creation --------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://www.youtube.com/watch?v=x", "https://127.0.0.1/v", "https://evil.example/v",
                                 "https://user:pw@youtube.com/v", "https://youtube.com:8443/v"])
def test_unsupported_urls_are_refused_at_creation(ws, url):
    resp = ws.new_job(source={"kind": "url", "url": url})
    assert resp.status_code == 422 and resp.json()["code"] == "UNSUPPORTED_URL"


@pytest.mark.parametrize("name,ok", [("งานแต่ง.mp4", True), ("C:\\Users\\me\\a.mp4", False), ("../a.mp4", False),
                                     ("notes.txt", False)])
def test_customer_file_is_referenced_by_name_only(ws, name, ok):
    resp = ws.new_job(source={"kind": "local_file", "file_name": name})
    assert resp.status_code == (201 if ok else 422)


def test_create_is_idempotent_and_records_rights_and_seed(ws):
    key = uuid.uuid4().hex
    first = ws.new_job(idempotency_key=key)
    again = ws.new_job(idempotency_key=key, requested_clips=7)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"] and again.json()["requested_clips"] == 3
    body = first.json()
    assert body["state"] == "RECEIVED" and isinstance(body["seed"], int)
    assert (body["clip_min_s"], body["clip_max_s"], body["subtitles"], body["review_mode"]) == (180, 300, True, "review")


def test_auto_mode_must_be_confirmed(ws):
    assert ws.new_job(review_mode="auto").status_code == 422
    assert ws.new_job(review_mode="auto", confirm_auto=True).json()["review_mode"] == "auto"


def test_jobs_are_tenant_scoped(ws, onboard):
    job = ws.new_job().json()
    other = onboard()
    assert other.get("/v1/jobs").json()["items"] == []
    assert other.get(f"/v1/jobs/{job['id']}").status_code == 404
    assert other.post(f"/v1/jobs/{job['id']}/cancel").status_code == 404
    resp = other.post("/v1/jobs", json={"idempotency_key": uuid.uuid4().hex, "environment_id": ws.env["id"],
                                        "source": {"kind": "url", "url": URL}})
    assert resp.status_code == 404


# --- happy path ------------------------------------------------------------------------------

def test_full_job_reserves_then_settles_each_clip(ws, app):
    job_id = ws.new_job(requested_clips=3).json()["id"]
    spec = ws.w.claim()
    assert spec["id"] == job_id and spec["source"]["url"] == URL and spec["clip_min_s"] == 180
    ws.w.run_to_rendering(job_id)
    for i in (1, 2, 3):
        assert ws.w.clip(job_id, i).status_code == 200
    done = ws.w.event(job_id, "completed").json()["job"]
    assert done["state"] == "READY_FOR_REVIEW"
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert [c["index"] for c in detail["clips"]] == [1, 2, 3]
    assert detail["clips"][0]["seed"] == detail["seed"] and detail["clips"][0]["template_version"] == "tpl-default-v2"
    assert detail["quota"] == {"reserved": 3, "settled": 3, "released": 0, "outstanding": 0}
    assert ws.get("/v1/workspace/usage").json()["clips"]["used"] == 3


def test_no_second_agent_gets_the_same_job(ws):
    ws.new_job()
    first, second = ws.w.claim(), ws.worker().claim()
    assert first is not None and second is None


# --- T09 short source --------------------------------------------------------------------------

def test_short_source_reduces_clip_count_and_says_so(ws):
    job_id = ws.new_job(requested_clips=5).json()["id"]
    ws.w.claim()
    job = ws.w.event(job_id, "source_validated", duration_s=700, possible_clips=2).json()["job"]
    assert job["planned_clips"] == 2
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert detail["notice"] == "INSUFFICIENT_SOURCE" and detail["quota"]["reserved"] == 2


def test_source_too_short_for_any_clip_charges_nothing(ws, app):
    job_id = ws.new_job().json()["id"]
    ws.w.claim()
    ws.w.event(job_id, "source_validated", duration_s=90, possible_clips=0)
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert detail["state"] == "FAILED" and detail["error"]["code"] == "INSUFFICIENT_SOURCE"
    assert ledger(app, job_id) == []


# --- T10 failure and repeated events -------------------------------------------------------------

def test_render_failure_releases_once_even_when_events_repeat(ws, app):
    job_id = ws.new_job(requested_clips=3).json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    clip_event = uuid.uuid4().hex
    assert ws.w.clip(job_id, 1, event_id=clip_event).json()["duplicate"] is False
    assert ws.w.clip(job_id, 1, event_id=clip_event).json()["duplicate"] is True      # redelivery
    assert ws.w.clip(job_id, 1).status_code == 200                                     # same clip, new event id
    fail_event = uuid.uuid4().hex
    assert ws.w.event(job_id, "failed", fail_event, code="RENDER_FAILED", detail="ffmpeg").status_code == 200
    assert ws.w.event(job_id, "failed", fail_event, code="RENDER_FAILED").json()["duplicate"] is True
    assert ws.w.event(job_id, "failed", code="RENDER_FAILED").json()["code"] == "JOB_NOT_ACTIVE"
    assert ledger(app, job_id) == [("release", 2, "job_failed_partial"), ("reserve", 3, "job_reserve"),
                                   ("settle", 1, "clip_delivered")]
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert detail["state"] == "READY_FOR_REVIEW" and detail["notice"] == "PARTIAL_RENDER"


def test_failure_before_any_clip_returns_everything(ws, app):
    job_id = ws.new_job(requested_clips=2).json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    ws.w.event(job_id, "failed", code="SOURCE_RATE_LIMITED", detail="bot check")
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert detail["state"] == "FAILED" and detail["quota"]["outstanding"] == 0
    assert ws.get("/v1/workspace/usage").json()["clips"]["used"] == 0


def test_completed_short_releases_the_rest(ws, app):
    job_id = ws.new_job(requested_clips=3).json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    ws.w.clip(job_id, 1)
    ws.w.event(job_id, "completed")
    assert ws.get(f"/v1/jobs/{job_id}").json()["quota"] == {"reserved": 3, "settled": 1, "released": 2,
                                                             "outstanding": 0}


def test_clip_with_a_different_file_for_the_same_index_is_refused(ws):
    job_id = ws.new_job().json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    ws.w.clip(job_id, 1)
    assert ws.w.clip(job_id, 1, digest=sha(99)).json()["code"] == "CLIP_CONFLICT"


@pytest.mark.parametrize("duration_ms", [60_000, 400_000])
def test_clip_outside_the_length_range_is_refused(ws, duration_ms):
    job_id = ws.new_job().json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    assert ws.w.clip(job_id, 1, duration_ms=duration_ms).json()["code"] == "CLIP_DURATION_OUT_OF_RANGE"


def test_events_out_of_order_or_unknown_are_refused(ws):
    job_id = ws.new_job().json()["id"]
    ws.w.claim()
    assert ws.w.clip(job_id, 1).json()["code"] == "BAD_EVENT_ORDER"
    assert ws.w.event(job_id, "teleport").json()["code"] == "UNKNOWN_EVENT"
    assert ws.w.event(job_id, "source_validated", duration_s=3600).json()["code"] == "VALIDATION_ERROR"
    ws.w.run_to_rendering(job_id)
    assert ws.w.event(job_id, "stage", stage="DOWNLOADING").json()["code"] == "BAD_EVENT_ORDER"


# --- T21 two jobs, last units ----------------------------------------------------------------------

def test_two_jobs_cannot_both_take_the_last_units(ws, app):
    a = ws.new_job(requested_clips=20).json()["id"]
    b = ws.new_job(requested_clips=20).json()["id"]
    w1, w2 = ws.w, ws.worker()
    claimed = {w1.claim()["id"]: w1, w2.claim()["id"]: w2}
    assert set(claimed) == {a, b}

    def validate(job_id):
        with TestClient(app) as c:
            w = claimed[job_id]
            return c.post(f"/v1/agent/jobs/{job_id}/events", headers={"Authorization": f"Bearer {w.session}"},
                          json={"event_id": uuid.uuid4().hex, "type": "source_validated", "duration_s": 36000,
                                "possible_clips": 20}).json()["job"]["state"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = sorted(pool.map(validate, [a, b]))
    assert states == ["NEEDS_ACTION", "SOURCE_VALIDATED"]
    usage = ws.get("/v1/workspace/usage").json()["clips"]
    assert usage["used"] == 20 and usage["available"] == 10
    blocked = next(j for j in (a, b) if ws.get(f"/v1/jobs/{j}").json()["state"] == "NEEDS_ACTION")
    assert ws.get(f"/v1/jobs/{blocked}").json()["error"]["code"] == "QUOTA_EXCEEDED"


# --- cancel and lost Agents ------------------------------------------------------------------------

def test_cancel_during_render_returns_held_quota_and_stops_the_agent(ws):
    job_id = ws.new_job(requested_clips=3).json()["id"]
    ws.w.claim()
    ws.w.run_to_rendering(job_id)
    ws.w.clip(job_id, 1)
    cancelled = ws.post(f"/v1/jobs/{job_id}/cancel").json()
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["quota"] == {"reserved": 3, "settled": 1, "released": 2, "outstanding": 0}
    assert ws.w.clip(job_id, 2).json()["code"] == "JOB_NOT_ACTIVE"
    assert ws.post(f"/v1/jobs/{job_id}/cancel").json()["code"] == "JOB_NOT_ACTIVE"


def test_cancel_before_validation_charges_nothing(ws, app):
    job_id = ws.new_job().json()["id"]
    assert ws.post(f"/v1/jobs/{job_id}/cancel").json()["state"] == "CANCELLED"
    assert ledger(app, job_id) == [] and ws.w.claim() is None


def _expire_lease(app, job_id):
    with app.state.db.sessionmaker() as s:
        s.execute(update(Job).where(Job.id == uuid.UUID(job_id))
                  .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()


def test_lost_agent_loses_the_lease_and_another_takes_over(ws):
    job_id = ws.new_job().json()["id"]
    old = ws.w
    old.claim()
    old.run_to_rendering(job_id)
    old.clip(job_id, 1)
    _expire_lease(ws.client.app, job_id)
    new = ws.worker()
    taken = new.claim()
    assert taken["id"] == job_id and taken["state"] == "RENDERING" and taken["planned_clips"] == 3
    assert old.clip(job_id, 2).json()["code"] == "LEASE_LOST"
    assert new.clip(job_id, 1).status_code == 200  # same clip again: no second charge
    assert ws.get(f"/v1/jobs/{job_id}").json()["quota"]["settled"] == 1


def test_job_fails_after_too_many_lost_agents(ws):
    job_id = ws.new_job().json()["id"]
    for attempt in range(3):
        # Each restart reuses the install (registration limit 2); the new session supersedes the old.
        w = ws.worker(ws.w.installation_id)
        assert w.claim()["id"] == job_id
        if attempt == 0:
            w.event(job_id, "source_validated", duration_s=3600, possible_clips=5)
        _expire_lease(ws.client.app, job_id)
    assert ws.worker(ws.w.installation_id).claim() is None
    detail = ws.get(f"/v1/jobs/{job_id}").json()
    assert detail["state"] == "FAILED" and detail["error"]["code"] == "AGENT_LOST"
    assert detail["quota"]["outstanding"] == 0


def test_agent_of_another_environment_cannot_touch_the_job(ws, onboard, client):
    job_id = ws.new_job().json()["id"]
    other = onboard()
    env = other.post("/v1/environments", json={"name": "x"}).json()
    token = other.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    intruder = _worker(client, other.username, token)
    assert intruder.claim() is None
    assert intruder.event(job_id, "source_validated", duration_s=1, possible_clips=1).status_code == 404


def test_api_allowlist_matches_the_agent_downloader():
    pytest.importorskip("yt_dlp")
    from clipflow_api.sources import PLATFORM_HOSTS as api_hosts
    from clipflow_worker.source import PLATFORM_HOSTS as worker_hosts

    assert api_hosts == worker_hosts
