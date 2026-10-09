"""P3.3 over real HTTP: the Agent job runner claims a job, runs the real P1 pipeline (ffmpeg,
silencedetect, libass render) on a customer file and delivers clips the server checks itself.

The source is a generated 70 s video with a 1 s pause every 10 s, so clips are cut at real audio
pauses. Linked sources (YouTube/Bilibili) need the network: test_real_source_job.py (opt-in).
"""

from __future__ import annotations

import subprocess
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from agent import job_runner
from agent.job_runner import JobRunner
from agent.server_client import ServerClient
from clipflow_api.models import Job
from clipflow_worker import pipeline
from clipflow_worker.media import binary
from clipflow_worker.render import Template


def _make_video(path, seconds):
    subprocess.run([
        binary("ffmpeg"), "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}",
        "-f", "lavfi", "-i", f"aevalsrc='if(lt(mod(t,10),9),0.5*sin(2*PI*440*t),0)':s=44100:d={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    ], check=True)


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("customer-media")
    _make_video(folder / "source.mp4", 70)
    _make_video(folder / "short.mp4", 10)
    return folder


class Shop:
    def __init__(self, owner, server_url, media_dir, data_dir):
        self.owner = owner
        self.env = owner.post("/v1/environments", json={"name": "office", "registered_agent_limit": 2,
                                                        "concurrent_session_limit": 2, "device_limit": 0}).json()
        token = owner.post("/v1/agent-tokens", json={"environment_id": self.env["id"], "name": "pc"}).json()["token"]
        self.client = ServerClient(server_url)
        self.session = self.client.authenticate(owner.username, token, str(uuid.uuid4()))
        self.logs = []
        self.runner = JobRunner(data_dir, media_dir, log=self.logs.append, keepalive_s=1.0, retry_wait_s=0.1)

    def job(self, file_name="source.mp4", clips=2, url=None):
        source = {"kind": "url", "url": url} if url else {"kind": "local_file", "file_name": file_name}
        resp = self.owner.post("/v1/jobs", json={
            "idempotency_key": uuid.uuid4().hex, "environment_id": self.env["id"],
            "source": source,
            "requested_clips": clips, "clip_min_s": 15, "clip_max_s": 25})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def run(self):
        return self.runner.run_once(self.client, lambda: self.session)

    def detail(self, job_id):
        return self.owner.get(f"/v1/jobs/{job_id}").json()


@pytest.fixture
def shop(onboard, server_url, media_dir, tmp_path):
    return Shop(onboard(), server_url, media_dir, tmp_path / "agent-data")


def test_local_file_job_end_to_end(shop, tmp_path):
    job_id = shop.job()
    assert shop.run() == "READY_FOR_REVIEW"

    job = shop.detail(job_id)
    assert job["planned_clips"] == 2 and job["notice"] is None
    assert job["quota"] == {"reserved": 2, "settled": 2, "released": 0, "outstanding": 0}
    for clip in job["clips"]:
        assert clip["uploaded"] and clip["check_status"] == "passed", clip["checks"]
        assert 15_000 <= clip["duration_ms"] <= 25_000
        # Cut at the middle of a real (1 s) pause (9.5 s, 19.5 s, ...), never mid-sound. The last pause
        # ends with the file, whose exact length depends on the AAC encoder of the ffmpeg build (CI saw
        # 69.504 s), so allow a few milliseconds while staying well inside the pause.
        for edge in (clip["start_ms"], clip["end_ms"]):
            assert abs(edge % 10_000 - 9_500) <= 50, edge
        assert clip["metadata"]["caption"] == f"source — ตอนที่ {clip['index']}/2"
        assert not clip["approval"]["approved"]  # review mode: a person approves
        # The Agent keeps the exact file it delivered, for posting later (Q-15).
        local = tmp_path / "agent-data" / "clips" / job_id / f"clip_{clip['index']:02d}.mp4"
        assert job_runner._sha256(local) == clip["render_sha256"]
    assert not (tmp_path / "agent-data" / "work" / job_id).exists()
    assert shop.run() is None  # nothing left to claim


def test_same_seed_reproduces_intervals_and_file(shop, media_dir, tmp_path):  # G3-02
    job_id = shop.job()
    assert shop.run() == "READY_FOR_REVIEW"
    job = shop.detail(job_id)
    p = pipeline.plan(work=tmp_path / "again", count=2, seed=job["seed"], min_len=15, max_len=25,
                      local=media_dir / "source.mp4")
    again = [(round(s.start * 1000), round(s.end * 1000)) for s in p.selection.segments]
    assert again == [(c["start_ms"], c["end_ms"]) for c in job["clips"]]
    first = p.selection.segments[0]
    result, _, _ = pipeline.render(p, 1, first, *pipeline.fetch_part(p, first), tmp_path / "again" / "c1.mp4",
                                   Template(burn_subtitles=True))
    assert result.sha256 == job["clips"][0]["render_sha256"]


def test_missing_customer_file_fails_without_charge(shop):
    job_id = shop.job("not-here.mp4")
    assert shop.run() == "FAILED"
    job = shop.detail(job_id)
    assert job["error"]["code"] == "SOURCE_NOT_FOUND"
    assert job["quota"]["reserved"] == 0
    assert "not-here.mp4" in job["error"]["detail"] and ":\\" not in job["error"]["detail"]


def test_short_source_is_refused_not_padded(shop):  # T09
    job_id = shop.job("short.mp4")
    assert shop.run() == "FAILED"
    job = shop.detail(job_id)
    assert job["error"]["code"] == "INSUFFICIENT_SOURCE" and job["clips"] == []
    assert job["quota"]["reserved"] == 0


def test_cancel_while_rendering_stops_the_agent(shop, monkeypatch):
    job_id = shop.job()
    real_render = pipeline.render

    def render_then_owner_cancels(*args, **kw):
        result = real_render(*args, **kw)
        assert shop.owner.post(f"/v1/jobs/{job_id}/cancel").status_code == 200
        return result

    monkeypatch.setattr(pipeline, "render", render_then_owner_cancels)
    assert shop.run() == "stopped"
    job = shop.detail(job_id)
    assert job["state"] == "CANCELLED"
    assert job["quota"] == {"reserved": 2, "settled": 0, "released": 2, "outstanding": 0}


def test_restart_mid_job_resumes_without_double_charge(shop, app, monkeypatch):
    job_id = shop.job()
    real_upload = job_runner._Job._upload
    calls = []

    def crash_on_second_upload(self, index, path):
        calls.append(index)
        if len(calls) == 2:
            raise KeyboardInterrupt  # the PC lost power after clip 2 was reported, before its upload
        return real_upload(self, index, path)

    monkeypatch.setattr(job_runner._Job, "_upload", crash_on_second_upload)
    with pytest.raises(KeyboardInterrupt):
        shop.run()
    first = shop.detail(job_id)
    assert [c["uploaded"] for c in first["clips"]] == [True, False]

    monkeypatch.setattr(job_runner._Job, "_upload", real_upload)
    with app.state.db.sessionmaker() as s:  # the lease of the lost run runs out
        s.execute(update(Job).where(Job.id == uuid.UUID(job_id))
                  .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    assert shop.run() == "READY_FOR_REVIEW"
    job = shop.detail(job_id)
    assert all(c["uploaded"] and c["check_status"] == "passed" for c in job["clips"])
    assert [c["render_sha256"] for c in job["clips"]][0] == first["clips"][0]["render_sha256"]
    assert job["quota"] == {"reserved": 2, "settled": 2, "released": 0, "outstanding": 0}
    assert any("ไฟล์เดิม" in line for line in shop.logs)  # clip 2 reused, not re-rendered


def test_source_pointing_at_an_internal_address_is_refused(shop, monkeypatch):  # T08 through the Agent flow
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import yt_dlp
    from yt_dlp.utils import DownloadError

    from clipflow_worker.source import _base_opts, _classify_download_error

    hits = []

    class Internal(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    internal = ThreadingHTTPServer(("127.0.0.1", 0), Internal)
    threading.Thread(target=internal.serve_forever, daemon=True).start()

    def inspect_that_lands_on_internal(url):
        # Stands in for a platform page whose media/redirect points at an internal service.
        try:
            with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
                ydl.extract_info(f"http://127.0.0.1:{internal.server_address[1]}/meta-data", download=False)
        except DownloadError as exc:
            raise _classify_download_error(exc) from exc

    monkeypatch.setattr(pipeline, "inspect", inspect_that_lands_on_internal)
    try:
        job_id = shop.job(url="https://www.youtube.com/watch?v=PBES5k67dhI")
        assert shop.run() == "FAILED"
    finally:
        internal.shutdown()
    job = shop.detail(job_id)
    assert job["error"]["code"] == "SOURCE_BLOCKED_ADDRESS"
    assert hits == []  # refused before any connection
    assert job["quota"]["reserved"] == 0
