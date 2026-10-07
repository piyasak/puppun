"""P3.2 / G3-03 / G3-05: clip upload with server-side hash, checks, preview, metadata versions, approval.

A real 16 s 1080x1920 H.264/AAC file is generated with ffmpeg so the 9:16 checks run on real media.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from api_test_agents import Agent

URL = "https://www.bilibili.tv/en/video/4800844531374592"


@pytest.fixture(scope="session")
def real_clip(tmp_path_factory) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=1080x1920:r=10:d=16",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=16", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True, timeout=120)
    return out.read_bytes()


class Worker(Agent):
    def event(self, job_id, type_, **payload):
        return self.post(f"/v1/agent/jobs/{job_id}/events", json={"event_id": uuid.uuid4().hex, "type": type_, **payload})

    def upload(self, job_id, index, body):
        return self.client.put(f"/v1/agent/jobs/{job_id}/clips/{index}/file", content=body,
                               headers={"Authorization": f"Bearer {self.session}"})

    def prepare(self, job_id, possible=3):
        self.post("/v1/agent/jobs/claim")
        self.event(job_id, "source_validated", duration_s=600, possible_clips=possible)
        for stage in ("DOWNLOADING", "ANALYZING", "RENDERING"):
            self.event(job_id, "stage", stage=stage)

    def report(self, job_id, index, body, duration_ms=16_000, **extra):
        return self.event(job_id, "clip_rendered", index=index, start_ms=0, end_ms=duration_ms,
                          duration_ms=duration_ms, sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                          template_version="tpl-default-v2", title="ชื่อคลิปในวิดีโอ", **extra)


@pytest.fixture
def ws(onboard, client):
    acc = onboard()
    env = acc.post("/v1/environments", json={"name": "office", "device_limit": 0}).json()
    token = acc.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    acc.w = Worker(client, acc.username, token)
    assert acc.w.auth().status_code == 200

    def new_job(mode="review", clips=2):
        body = {"idempotency_key": uuid.uuid4().hex, "environment_id": env["id"], "requested_clips": clips,
                "source": {"kind": "url", "url": URL}, "clip_min_s": 15, "clip_max_s": 20, "review_mode": mode}
        if mode == "auto":
            body["confirm_auto"] = True
        job_id = acc.post("/v1/jobs", json=body).json()["id"]
        acc.w.prepare(job_id)
        return job_id

    acc.new_job = new_job
    return acc


def delivered(ws, job_id, body, index=1, **extra):
    assert ws.w.report(job_id, index, body, **extra).status_code == 200
    resp = ws.w.upload(job_id, index, body)
    assert resp.status_code == 200, resp.text
    return ws.get(f"/v1/jobs/{job_id}").json()["clips"][index - 1]


# --- upload -------------------------------------------------------------------------------------

def test_upload_is_hashed_by_the_server_and_settles_quota_only_then(ws, real_clip):
    job_id = ws.new_job()
    ws.w.report(job_id, 1, real_clip)
    assert ws.get(f"/v1/jobs/{job_id}").json()["quota"]["settled"] == 0  # announced, not delivered
    tampered = real_clip[:-1] + bytes([real_clip[-1] ^ 1])
    bad = ws.w.upload(job_id, 1, tampered)
    assert bad.status_code == 422 and bad.json()["code"] == "HASH_MISMATCH"
    ok = ws.w.upload(job_id, 1, real_clip)
    assert ok.status_code == 200 and ok.json()["check_status"] == "passed"
    assert ws.w.upload(job_id, 1, real_clip).status_code == 200  # same file again: no-op
    job = ws.get(f"/v1/jobs/{job_id}").json()
    assert job["quota"]["settled"] == 1 and job["clips"][0]["uploaded"] is True


def test_real_file_passes_the_9_16_checks(ws, real_clip):
    clip = delivered(ws, ws.new_job(), real_clip)
    checks = {c["name"]: c for c in clip["checks"]["checks"]}
    assert all(c["ok"] for c in checks.values()), checks
    assert checks["size_9_16"]["detail"] == "1080x1920" and checks["audio_stream"]["detail"] == "aac"


def test_upload_rules(ws, real_clip):
    job_id = ws.new_job()
    assert ws.w.upload(job_id, 1, real_clip).status_code == 404  # not reported yet
    ws.w.report(job_id, 1, real_clip)
    assert ws.w.event(job_id, "completed").json()["code"] == "CLIPS_NOT_UPLOADED"
    other = Worker(ws.w.client, ws.username, ws.w.token)  # second install, no lease
    assert other.auth().status_code == 409  # session limit 1; supersede instead:
    other = Worker(ws.w.client, ws.username, ws.w.token, ws.w.installation_id)
    other.auth()
    assert ws.w.upload(job_id, 1, real_clip).status_code == 401  # old session fenced
    assert other.upload(job_id, 1, real_clip).json()["code"] == "LEASE_LOST"


def test_completed_job_takes_no_more_uploads(ws, real_clip):
    job_id = ws.new_job(clips=1)
    delivered(ws, job_id, real_clip)
    assert ws.w.event(job_id, "completed").json()["job"]["state"] == "READY_FOR_REVIEW"
    assert ws.w.upload(job_id, 1, real_clip).json()["code"] == "JOB_NOT_ACTIVE"


# --- preview ------------------------------------------------------------------------------------

def test_preview_link_is_short_lived_signed_and_owner_only(ws, onboard, real_clip, client):
    clip = delivered(ws, ws.new_job(), real_clip)
    link = ws.get(f"/v1/clips/{clip['id']}/media").json()
    assert link["expires_in_s"] == 300
    path = urlsplit(link["url"])
    full = client.get(f"{path.path}?{path.query}")
    assert full.status_code == 200 and full.content == real_clip and full.headers["content-type"] == "video/mp4"
    part = client.get(f"{path.path}?{path.query}", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100  # seeking works

    q = parse_qs(path.query)
    assert client.get(f"{path.path}?exp={q['exp'][0]}&sig={'0' * 64}").status_code == 404
    assert client.get(f"{path.path}?exp={int(time.time()) - 1}&sig={q['sig'][0]}").status_code == 404
    assert onboard().get(f"/v1/clips/{clip['id']}/media").status_code == 404


# --- metadata -----------------------------------------------------------------------------------

def test_metadata_versions_and_rules(ws, real_clip):
    clip = delivered(ws, ws.new_job(), real_clip, caption="แคปชันแรก 🎬", hashtags=["ตลก", "#Funny"])
    assert clip["metadata"] == {"version": 1, "caption": "แคปชันแรก 🎬", "hashtags": ["#ตลก", "#Funny"]}
    cid = clip["id"]
    v2 = ws.patch(f"/v1/clips/{cid}/metadata", json={"expected_version": 1, "hashtags": ["a", "#A", "ข่าว"]}).json()
    assert v2["metadata"] == {"version": 2, "caption": "แคปชันแรก 🎬", "hashtags": ["#a", "#ข่าว"]}
    stale = ws.patch(f"/v1/clips/{cid}/metadata", json={"expected_version": 1, "caption": "x"})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    title = ws.patch(f"/v1/clips/{cid}/metadata", json={"expected_version": 2, "title": "ชื่อใหม่"})
    assert title.json()["code"] == "RERENDER_REQUIRED"
    assert ws.patch(f"/v1/clips/{cid}/metadata", json={"expected_version": 2, "hashtags": ["bad tag"]}).status_code == 422
    history = ws.get(f"/v1/clips/{cid}").json()["metadata_history"]
    assert [h["version"] for h in history] == [2, 1]


# --- approval (G3-05) -----------------------------------------------------------------------------

def test_review_mode_needs_a_person_and_edits_void_the_approval(ws, real_clip):
    clip = delivered(ws, ws.new_job(), real_clip)
    cid = clip["id"]
    assert clip["approval"]["approved"] is False
    assert ws.post(f"/v1/clips/{cid}/approve", json={"metadata_version": 1}).json()["approval"]["mode"] == "manual"
    edited = ws.patch(f"/v1/clips/{cid}/metadata", json={"expected_version": 1, "caption": "แก้แล้ว"}).json()
    assert edited["approval"]["approved"] is False  # approval was for version 1
    old = ws.post(f"/v1/clips/{cid}/approve", json={"metadata_version": 1})
    assert old.status_code == 409 and old.json()["code"] == "VERSION_CONFLICT"
    assert ws.post(f"/v1/clips/{cid}/approve", json={"metadata_version": 2}).json()["approval"]["approved"] is True
    assert ws.post(f"/v1/clips/{cid}/unapprove").json()["approval"]["approved"] is False


def test_clip_that_failed_checks_cannot_be_approved(ws):
    junk = b"not a video at all"
    clip = delivered(ws, ws.new_job(), junk)
    assert clip["check_status"] == "failed"
    resp = ws.post(f"/v1/clips/{clip['id']}/approve", json={"metadata_version": 1})
    assert resp.status_code == 409 and resp.json()["code"] == "CHECKS_FAILED"


def test_not_uploaded_clip_cannot_be_approved(ws, real_clip):
    job_id = ws.new_job()
    ws.w.report(job_id, 1, real_clip)
    cid = ws.get(f"/v1/jobs/{job_id}").json()["clips"][0]["id"]
    assert ws.post(f"/v1/clips/{cid}/approve", json={"metadata_version": 1}).json()["code"] == "CLIP_NOT_UPLOADED"


def test_auto_mode_approves_only_clips_that_pass_every_check(ws, real_clip):
    job_id = ws.new_job(mode="auto")
    good = delivered(ws, job_id, real_clip, index=1)
    bad = delivered(ws, job_id, b"broken file", index=2)
    assert good["approval"] == good["approval"] | {"approved": True, "mode": "auto"}
    assert bad["approval"]["approved"] is False and bad["check_status"] == "failed"
    # Editing the caption in auto mode re-applies the policy to the new version.
    edited = ws.patch(f"/v1/clips/{good['id']}/metadata", json={"expected_version": 1, "caption": "ใหม่"}).json()
    assert edited["approval"]["approved"] is True and edited["approval"]["metadata_version"] == 2


def test_clips_are_tenant_scoped(ws, onboard, real_clip):
    clip = delivered(ws, ws.new_job(), real_clip)
    other = onboard()
    for resp in (other.get(f"/v1/clips/{clip['id']}"),
                 other.post(f"/v1/clips/{clip['id']}/approve", json={"metadata_version": 1}),
                 other.patch(f"/v1/clips/{clip['id']}/metadata", json={"expected_version": 1, "caption": "x"})):
        assert resp.status_code == 404
    assert ws.get(f"/v1/clips/{clip['id']}").json()["approval"]["approved"] is False
