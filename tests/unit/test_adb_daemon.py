"""The adb daemon start race (QA PC, 2026-10-10) and which adb the Agent uses. Logic only; the
packaged adb is checked with the built exe."""

from __future__ import annotations

import subprocess

import pytest

from agent import adb as adbmod
from agent.adb import AdbError, daemon_down, default_runner

RACE = ("* daemon not running; starting now at tcp:5037\ncould not read ok from ADB Server\n"
        "* failed to start daemon\nadb.EXE: failed to check server version: cannot connect to daemon")


class Calls:
    def __init__(self, *results):
        self.results, self.args = list(results), []

    def __call__(self, args, **kw):
        self.args.append(args[1:])
        if args[1] == "start-server":
            return subprocess.CompletedProcess(args, 0, "", "")
        code, out, err = self.results.pop(0)
        return subprocess.CompletedProcess(args, code, out, err)


def test_the_seen_message_is_a_daemon_problem():
    assert daemon_down(RACE)
    assert not daemon_down("error: device unauthorized.")
    assert not daemon_down("adb: error: failed to copy 'a' to 'b': remote No space left on device")


def test_daemon_down_starts_the_server_once_and_repeats_the_command():
    calls = Calls((1, "", RACE), (0, "List of devices attached\nX\tdevice\n", ""))
    run = default_runner("adb.exe", call=calls, sleep=lambda s: None)
    assert "X\tdevice" in run(["devices", "-l"])
    assert calls.args == [["devices", "-l"], ["start-server"], ["devices", "-l"]]


def test_other_errors_are_not_repeated():
    calls = Calls((1, "", "error: device unauthorized."))
    with pytest.raises(AdbError, match="unauthorized"):
        default_runner("adb.exe", call=calls, sleep=lambda s: None)(["devices"])
    assert calls.args == [["devices"]]


def test_gives_up_after_the_retries():
    calls = Calls(*[(1, "", RACE)] * 3)
    with pytest.raises(AdbError, match="cannot connect to daemon"):
        default_runner("adb.exe", retries=2, call=calls, sleep=lambda s: None)(["devices"])
    assert [a for a in calls.args if a == ["devices"]] == [["devices"]] * 3


def test_the_agents_own_adb_comes_before_path(tmp_path, monkeypatch):
    own = tmp_path / "adb" / "adb.exe"
    own.parent.mkdir()
    own.write_bytes(b"MZ")
    monkeypatch.delenv("CLIPFLOW_ADB", raising=False)
    monkeypatch.setattr(adbmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(adbmod.sys, "executable", str(tmp_path / "punpun-agent.exe"))
    monkeypatch.setattr(adbmod.shutil, "which", lambda name: r"C:\Android\platform-tools\adb.exe")
    assert adbmod.find_adb() == str(own)
    own.unlink()
    assert adbmod.find_adb() == r"C:\Android\platform-tools\adb.exe"  # fallback: PATH


def test_an_empty_list_right_after_a_daemon_start_is_asked_again():
    calls = Calls((0, "List of devices attached\n\n", ""), (0, "List of devices attached\nX\tdevice\n", ""))
    assert "X\tdevice" in default_runner("adb.exe", call=calls, sleep=lambda s: None)(["devices", "-l"])
    calls = Calls(*[(0, "List of devices attached\n\n", "")] * 4)
    waits = []
    assert default_runner("adb.exe", call=calls, sleep=waits.append)(["devices"]).strip() == "List of devices attached"
    assert len(calls.args) == 4 and sum(waits) == 5.0  # no phone really: about 5 s, not forever
