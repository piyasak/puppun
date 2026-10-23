"""Unexpected errors on this PC (PO 2026-10-23): the web sees what and which file; agent.log gets the traceback."""

from __future__ import annotations

import logging
import os

from agent import errors


def test_a_missing_file_names_the_file_but_not_the_users_folders():
    home = os.path.expanduser("~")
    exc = FileNotFoundError(2, "The system cannot find the file specified", os.path.join(home, "AppData", "x", "ffprobe.exe"))
    text = errors.summary(exc)
    assert text == "FileNotFoundError: [Errno 2] The system cannot find the file specified ffprobe.exe"
    assert home.lower() not in text.lower()


def test_other_errors_keep_their_message_on_one_short_line():
    assert errors.summary(RuntimeError("boom")) == "RuntimeError: boom"
    assert errors.summary(KeyError("clips")) == "KeyError: 'clips'"
    assert errors.summary(ValueError()) == "ValueError"
    long = errors.summary(RuntimeError("x\n" * 400))
    assert len(long) <= errors.MAX_LEN and "\n" not in long
    assert "%USERPROFILE%" in errors.summary(RuntimeError(r"open C:\Users\someone\Videos\a.mp4 failed"))


def test_record_writes_the_traceback_to_the_log(caplog):
    try:
        raise FileNotFoundError(2, "No such file", "node.exe")
    except FileNotFoundError as exc:
        with caplog.at_level(logging.ERROR, logger="punpun.agent"):
            detail = errors.record("job 1234", exc)
    assert detail.endswith("node.exe")
    assert "Traceback" in caplog.text and "job 1234" in caplog.text
