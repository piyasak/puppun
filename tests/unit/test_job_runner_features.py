"""Q-33: the Agent only takes clip jobs from a server that can take a clip kept on this PC.
Seen on staging 2026-10-09: an older server (no PUT .../preview) failed the job after the whole render."""

from __future__ import annotations

import clipflow_worker.media
from agent.server_client import Session


class Client:
    def __init__(self):
        self.claims = 0

    def claim_job(self, session):
        self.claims += 1
        return None


def runner(tmp_path, monkeypatch, logs):
    from agent import clips_folder
    from agent.job_runner import JobRunner

    monkeypatch.setattr(clipflow_worker.media, "ensure_on_path", lambda: "")
    monkeypatch.setattr(clips_folder, "has_room", lambda folder: True)  # not this PC's free space
    return JobRunner(tmp_path / "data", tmp_path / "media", log=logs.append, clips_dir=tmp_path / "clips")


def test_no_claim_from_a_server_without_kept_clips(tmp_path, monkeypatch):
    logs, client = [], Client()
    r = runner(tmp_path, monkeypatch, logs)
    old = Session("cfas_x", 1, {"id": "e", "name": "office"}, 15)  # a server from before Q-33 sends no features
    assert r.run_once(client, lambda: old) is None
    assert r.run_once(client, lambda: old) is None
    assert client.claims == 0
    assert len(logs) == 1 and "ต้องอัปเดต Server" in logs[0]  # said once, not every poll


def test_claims_when_the_server_takes_kept_clips(tmp_path, monkeypatch):
    logs, client = [], Client()
    r = runner(tmp_path, monkeypatch, logs)
    new = Session("cfas_x", 1, {"id": "e", "name": "office"}, 15, ("clip_preview",))
    assert r.run_once(client, lambda: new) is None
    assert client.claims == 1 and logs == []
