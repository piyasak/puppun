"""A PC without FFmpeg (2026-10-12): the Agent keeps running, only clip jobs wait, and says why once."""

from __future__ import annotations

from types import SimpleNamespace

from agent.job_runner import JobRunner
from clipflow_worker import media


class Client:
    def __init__(self):
        self.claims = 0

    def claim_job(self, session):
        self.claims += 1
        return None


def test_no_ffmpeg_waits_for_jobs_and_picks_it_up_once_installed(tmp_path, monkeypatch):
    installed = {"yes": False}

    def ensure():
        if not installed["yes"]:
            raise FileNotFoundError("ffmpeg not found; install FFmpeg or set FFMPEG_DIR")
        return "C:/ffmpeg/bin"

    monkeypatch.setattr(media, "ensure_on_path", ensure)
    logs, client = [], Client()
    runner = JobRunner(tmp_path, log=logs.append, clips_dir=tmp_path / "clips")  # no exception
    session = SimpleNamespace(features=["clip_preview"])
    for _ in range(3):
        assert runner.run_once(client, lambda: session) is None
    assert client.claims == 0 and sum("ไม่พบ FFmpeg" in line for line in logs) == 1
    installed["yes"] = True
    assert runner.run_once(client, lambda: session) is None
    assert client.claims == 1 and "พบ FFmpeg แล้ว" in logs[-1]
