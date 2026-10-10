"""The settings window's logic (PO 2026-10-10): pairing, folders, start with Windows. Logic only."""

from __future__ import annotations

import sys

import pytest

from agent import settings
from agent.credentials import AgentConfig, load_config, save_config
from agent.server_client import ServerError


class Client:
    def __init__(self, server, answer=None, error=None):
        self.base, self.answer, self.error, self.sent = server.rstrip("/"), answer, error, None

    def pair(self, code, computer_name):
        self.sent = (code, computer_name)
        if self.error:
            raise self.error
        return self.answer


def test_pairing_saves_server_username_and_the_token_encrypted(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(settings, "save_token", lambda data, token: saved.update(token=token))
    save_config(tmp_path, AgentConfig("https://old", "old", r"D:\punpun\clips", r"D:\Videos"))
    made = []

    def factory(server):
        made.append(Client(server, {"username": "shop1", "token": "cfat_x", "environment": {"name": "office"}}))
        return made[0]

    result = settings.pair(tmp_path, "https://punpun.example/", "abcd-efgh", factory)
    assert result == {"username": "shop1", "environment": "office"}
    cfg = load_config(tmp_path)
    assert (cfg.server, cfg.username) == ("https://punpun.example", "shop1")
    assert (cfg.clips_dir, cfg.media_dir) == (r"D:\punpun\clips", r"D:\Videos")  # folders kept
    assert saved == {"token": "cfat_x"} and made[0].sent[0] == "abcd-efgh"


def test_pairing_errors_are_shown_not_raised(tmp_path):
    def refused(server):
        return Client(server, error=ServerError(400, "PAIRING_CODE_INVALID", "รหัสเชื่อมต่อไม่ถูกต้อง", None))

    with pytest.raises(settings.SettingsError, match="รหัสเชื่อมต่อไม่ถูกต้อง"):
        settings.pair(tmp_path, "https://punpun.example", "WRONG-CODE", refused)
    with pytest.raises(settings.SettingsError, match="ใส่รหัส"):
        settings.pair(tmp_path, "https://punpun.example", "  ", refused)
    assert load_config(tmp_path) is None  # nothing saved


def test_folders_are_checked_and_remembered(tmp_path):
    save_config(tmp_path / "data", AgentConfig("https://s", "u"))
    videos = tmp_path / "videos"
    videos.mkdir()
    clips, media = settings.save_folders(tmp_path / "data", str(tmp_path / "clips"), f'"{videos}"')
    cfg = load_config(tmp_path / "data")
    assert cfg.clips_dir == str(clips) and clips.is_dir() and cfg.media_dir == str(media)
    with pytest.raises(settings.SettingsError, match="วิดีโอ"):
        settings.save_folders(tmp_path / "data", str(tmp_path / "clips"), str(tmp_path / "missing"))
    with pytest.raises(settings.SettingsError, match="คลิป"):
        settings.save_folders(tmp_path / "data", "relative\\clips", "")


def test_folders_need_an_account_first(tmp_path):
    with pytest.raises(settings.SettingsError, match="เชื่อมต่อบัญชีก่อน"):
        settings.save_folders(tmp_path, str(tmp_path / "clips"), "")


def test_moving_the_clips_folder_brings_the_clips_made(tmp_path):
    data = tmp_path / "data"
    save_config(data, AgentConfig("https://s", "u", str(tmp_path / "old")))
    (tmp_path / "old" / "job-1").mkdir(parents=True)
    (tmp_path / "old" / "job-1" / "clip_01.mp4").write_bytes(b"x")
    settings.save_folders(data, str(tmp_path / "new"), "")
    assert (tmp_path / "new" / "job-1" / "clip_01.mp4").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcut (WScript.Shell)")
def test_start_with_windows_is_a_startup_shortcut(tmp_path):
    launcher = tmp_path / "punpun-agent.cmd"
    launcher.write_text("@echo off\r\n", encoding="ascii")
    assert not settings.autostart_on(tmp_path)
    settings.set_autostart(True, launcher, tmp_path)
    assert settings.autostart_on(tmp_path)
    settings.set_autostart(False, launcher, tmp_path)
    assert not settings.autostart_on(tmp_path)
