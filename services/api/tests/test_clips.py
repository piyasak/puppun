"""P3.2 / G3-03 / G3-05: clip upload with server-side hash, checks, preview, metadata versions, approval.

A real 16 s 1080x1920 H.264/AAC file is generated with ffmpeg so the 9:16 checks run on real media.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from api_test_shop import Worker

URL = "https://www.bilibili.tv/en/video/4800844531374592"


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
    # No server paths in what the customer sees (ffprobe's error names the server's temp file).
    assert clip["checks"]["checks"] == [{"name": "readable", "ok": False, "detail": "not a readable video file"}]
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


# --- Q-33: the file stays on the Agent's PC; checks + a still are delivered --------------------------

JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"still-image-bytes"
PASSED = {"status": "passed", "checks": [{"name": "size_9_16", "ok": True, "detail": "1080x1920"},
                                          {"name": "audio_stream", "ok": True, "detail": "aac"}]}


def kept_on_agent(ws, job_id, body, index=1, checks=PASSED, still=JPEG):
    assert ws.w.report(job_id, index, body, checks=checks, local_path=f"D:\punpun\clips\{job_id}\clip_{index:02d}.mp4"
                       ).status_code == 200
    return ws.w.client.put(f"/v1/agent/jobs/{job_id}/clips/{index}/preview", content=still,
                           headers={"Authorization": f"Bearer {ws.w.session}", "Content-Type": "image/jpeg"})


def test_clip_kept_on_the_agent_is_delivered_with_checks_and_a_still(ws, real_clip, client):
    job_id = ws.new_job()
    assert kept_on_agent(ws, job_id, real_clip).status_code == 200
    clip = ws.get(f"/v1/jobs/{job_id}").json()["clips"][0]
    assert clip["uploaded"] and clip["file_location"] == "agent" and clip["preview"] == "image"
    assert clip["agent_path"].endswith("clip_01.mp4") and clip["check_status"] == "passed"
    assert clip["checks"]["by"] == "agent"
    assert ws.get(f"/v1/jobs/{job_id}").json()["quota"]["settled"] == 1  # settled on delivery, as before
    media = ws.get(f"/v1/clips/{clip['id']}/media").json()
    assert media["kind"] == "image"
    still = client.get(media["url"])
    assert still.status_code == 200 and still.headers["content-type"] == "image/jpeg" and still.content == JPEG
    assert ws.post(f"/v1/clips/{clip['id']}/approve", json={"metadata_version": 1}).status_code == 200
    # Posting reads the Agent's own file: no download link for a clip that never left the PC.
    assert kept_on_agent(ws, job_id, real_clip).status_code == 200  # repeated delivery: nothing changes


def test_a_still_needs_reported_checks_and_must_be_a_small_jpeg(ws, real_clip):
    job_id = ws.new_job()
    assert ws.w.report(job_id, 1, real_clip).status_code == 200  # no checks reported (an old Agent)
    put = lambda body: ws.w.client.put(f"/v1/agent/jobs/{job_id}/clips/1/preview", content=body,  # noqa: E731
                                       headers={"Authorization": f"Bearer {ws.w.session}"})
    assert put(JPEG).json()["code"] == "CHECKS_NOT_REPORTED"
    assert ws.w.report(job_id, 1, real_clip, checks=PASSED).status_code == 200
    assert put(b"GIF89a....").json()["code"] == "PREVIEW_NOT_JPEG"
    assert put(JPEG + b"x" * (2 * 1024 * 1024)).json()["code"] == "PREVIEW_TOO_LARGE"
    assert put(JPEG).status_code == 200


def test_reported_checks_cannot_claim_a_pass_they_do_not_show(ws, real_clip):
    job_id = ws.new_job(mode="auto")
    lying = {"status": "passed", "checks": [{"name": "size_9_16", "ok": False, "detail": "720x1280"}]}
    assert kept_on_agent(ws, job_id, real_clip, checks=lying).status_code == 200
    clip = ws.get(f"/v1/jobs/{job_id}").json()["clips"][0]
    assert clip["check_status"] == "failed" and not clip["approval"]["approved"]  # auto mode approves only a pass
    assert ws.post(f"/v1/clips/{clip['id']}/approve", json={"metadata_version": 1}).json()["code"] == "CHECKS_FAILED"


def test_auto_mode_approves_a_clip_kept_on_the_agent_that_passed(ws, real_clip):
    job_id = ws.new_job(mode="auto")
    assert kept_on_agent(ws, job_id, real_clip).status_code == 200
    assert ws.get(f"/v1/jobs/{job_id}").json()["clips"][0]["approval"]["approved"]
