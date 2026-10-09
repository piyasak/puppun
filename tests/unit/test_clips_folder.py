"""Q-33: the folder that keeps finished clips on the Agent's PC."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import clips_folder
from agent.credentials import AgentConfig, load_config, save_config


def test_folder_must_be_absolute_and_writable(tmp_path):
    assert clips_folder.check(tmp_path / "new" / "clips") == (tmp_path / "new" / "clips").resolve()
    with pytest.raises(clips_folder.FolderError):
        clips_folder.check(Path("relative/clips"))


def test_chosen_folder_is_remembered_and_old_installs_keep_their_folder(tmp_path):
    data = tmp_path / "data"
    save_config(data, AgentConfig("https://s", "u"))  # an install from before Q-33
    assert clips_folder.current(data) == data / "clips"
    save_config(data, AgentConfig("https://s", "u", str(tmp_path / "videos")))
    assert load_config(data).clips_dir == str(tmp_path / "videos")
    assert clips_folder.search_order(data) == [tmp_path / "videos", data / "clips"]  # old clips still found


def test_moving_keeps_every_job_folder(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "job-a").mkdir(parents=True)
    (old / "job-a" / "clip_01.mp4").write_bytes(b"x")
    new.mkdir()
    assert clips_folder.move_jobs(old, new) == 1
    assert (new / "job-a" / "clip_01.mp4").read_bytes() == b"x"


def test_no_new_job_without_room(tmp_path, monkeypatch):
    from agent.job_runner import JobRunner

    monkeypatch.setattr(clips_folder, "free_bytes", lambda folder: 1 * 1024**3)
    logs = []

    class NoClaim:
        def claim_job(self, session):
            raise AssertionError("must not claim a job without disk space")

    runner = JobRunner(tmp_path, None, log=logs.append, clips_dir=tmp_path / "clips")
    assert runner.run_once(NoClaim(), lambda: None) is None
    assert "ยังไม่รับงานใหม่" in logs[0]
