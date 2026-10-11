"""Videos folder list and jobs from clips already cut (PO 2026-10-11), over real HTTP with the real
Agent job runner: a sub-folder of the videos folder becomes one job, its .mp4 files clips in EP order,
nothing cut or rendered, the originals untouched."""

from __future__ import annotations

import subprocess
import uuid

import pytest
from test_agent_job_runner_http import Shop, _make_video

from agent import clips_folder
from agent.job_runner import JobRunner
from agent.library import LibraryWorker, scan
from clipflow_worker.media import binary


def _silent_video(path, seconds):
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=360x640:rate=25:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    str(path)], check=True)


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    root = tmp_path_factory.mktemp("videos")
    _make_video(root / "เรื่องเต็ม.mp4", 12)
    series = root / "เรื่องA"
    series.mkdir()
    for name, seconds in (("EP10.mp4", 3), ("EP2.mp4", 2), ("EP1.mp4", 4)):
        _make_video(series / name, seconds)
    (series / "notes.txt").write_text("not a clip", encoding="utf-8")
    (series / "EP3.mkv").write_bytes(b"mkv is not posted as it is")
    silent = root / "ไม่มีเสียง"
    silent.mkdir()
    _silent_video(silent / "EP1.mp4", 2)
    return root


@pytest.fixture
def ready(onboard, server_url, videos, tmp_path, monkeypatch):
    monkeypatch.setattr(clips_folder, "has_room", lambda folder: True)
    shop = Shop(onboard(), server_url, videos, tmp_path / "agent-data")
    shop.clips_dir = tmp_path / "clips"
    shop.runner = JobRunner(tmp_path / "agent-data", videos, log=shop.logs.append, keepalive_s=1.0,
                            retry_wait_s=0.1, clips_dir=shop.clips_dir)
    return shop


def make(shop, folder, mode="review"):
    body = {"idempotency_key": uuid.uuid4().hex, "environment_id": shop.env["id"],
            "source": {"kind": "local_clips", "folder": folder}, "review_mode": mode, "delete_after_post": True}
    if mode == "auto":
        body["confirm_auto"] = True
    resp = shop.owner.post("/v1/jobs", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_scan_lists_full_videos_and_folders_of_clips_in_ep_order(videos):
    lib = scan(videos)
    assert [v["name"] for v in lib["videos"]] == ["เรื่องเต็ม.mp4"]
    sets = {s["folder"]: s["clips"] for s in lib["sets"]}
    assert sets["เรื่องA"] == ["EP1.mp4", "EP2.mp4", "EP10.mp4"]  # natural order, .mp4 only
    assert sets["ไม่มีเสียง"] == ["EP1.mp4"]


def test_the_agent_reports_the_folder_and_the_web_reads_it(ready, onboard, videos):
    session = ready.session
    assert "video_library" in session.features
    worker = LibraryWorker(videos)
    assert worker.report_once(ready.client, session) is True
    assert worker.report_once(ready.client, session) is False  # unchanged: not sent again
    lib = ready.owner.get(f"/v1/environments/{ready.env['id']}/library").json()
    assert lib["reported_at"] and [v["name"] for v in lib["videos"]] == ["เรื่องเต็ม.mp4"]
    a = next(s for s in lib["sets"] if s["folder"] == "เรื่องA")
    assert a["count"] == 3 and a["clips"] == ["EP1.mp4", "EP2.mp4", "EP10.mp4"]
    # Names only: a path or a junk name sent by a modified Agent is dropped.
    ready.client.report_library(session, {"videos": [{"name": "..\\secret.mp4", "size_bytes": 1}],
                                          "sets": [{"folder": "C:/x", "clips": ["a.mp4"]}]})
    assert ready.owner.get(f"/v1/environments/{ready.env['id']}/library").json() | {"reported_at": None} == \
        {"reported_at": None, "videos": [], "sets": []}
    assert onboard().get(f"/v1/environments/{ready.env['id']}/library").status_code == 404


def test_older_agents_never_get_a_job_from_clips_already_cut(ready):
    job = make(ready, "เรื่องA")
    old = ready.client._post("/v1/agent/jobs/claim", {}, bearer=ready.session.token)["job"]  # Agent 0.4.x: no kinds
    assert old is None
    spec = ready.client.claim_job(ready.session)
    assert spec["id"] == job["id"] and spec["source"]["kind"] == "local_clips"


def test_a_folder_of_clips_becomes_one_job_in_ep_order(ready, videos):
    before = {p.name: p.read_bytes() for p in (videos / "เรื่องA").iterdir()}
    job = make(ready, "เรื่องA")
    assert job["subtitles"] is False and job["delete_after_post"] is False  # the originals are never deleted
    assert ready.run() == "READY_FOR_REVIEW"
    detail = ready.detail(job["id"])
    assert detail["planned_clips"] == 3 and detail["quota"]["settled"] == 3
    clips = detail["clips"]
    assert [c["metadata"]["caption"] for c in clips] == ["EP1", "EP2", "EP10"]
    assert [round(c["duration_ms"] / 1000) for c in clips] == [4, 2, 3]
    assert all(c["check_status"] == "passed" and c["preview"] == "image" for c in clips)
    home = ready.clips_dir / job["id"]
    assert (home / "clip_01.mp4").read_bytes() == before["EP1.mp4"]  # linked as it is, for posting
    assert {p.name: p.read_bytes() for p in (videos / "เรื่องA").iterdir()} == before  # originals untouched
    assert ready.owner.post(f"/v1/clips/{clips[0]['id']}/approve", json={"metadata_version": 1}).status_code == 200


def test_a_clip_without_sound_fails_its_checks_and_cannot_be_approved(ready):
    job = make(ready, "ไม่มีเสียง", mode="auto")
    assert ready.run() == "READY_FOR_REVIEW"
    clip = ready.detail(job["id"])["clips"][0]
    assert clip["check_status"] == "failed" and clip["approval"]["approved"] is False  # auto mode approves only passed clips
    failed = {c["name"] for c in clip["checks"]["checks"] if not c["ok"]}
    assert failed == {"audio_stream"}
    assert ready.owner.post(f"/v1/clips/{clip['id']}/approve", json={"metadata_version": 1}).json()["code"] == "CHECKS_FAILED"


def test_a_missing_folder_fails_the_job(ready):
    job = make(ready, "ไม่มีโฟลเดอร์นี้")
    assert ready.run() == "FAILED"
    assert ready.detail(job["id"])["error"]["code"] == "SOURCE_NOT_FOUND"


def test_folder_names_only(ready):
    resp = ready.owner.post("/v1/jobs", json={"idempotency_key": uuid.uuid4().hex, "environment_id": ready.env["id"],
                                              "source": {"kind": "local_clips", "folder": "..\\อื่น"}})
    assert resp.status_code == 422 and resp.json()["code"] == "UNSUPPORTED_FOLDER"

