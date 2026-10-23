"""FFmpeg failing to join video and audio (customer PC, 2026-10-19): try again once, keep FFmpeg's own words."""

from __future__ import annotations

import shutil
import subprocess

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

from clipflow_worker import source

FFMPEG = shutil.which("ffmpeg")
BAD = "ERROR: Postprocessing: ffmpeg exited with code 3436169992"


def test_a_merge_failure_is_told_apart_and_its_code_is_readable():
    assert source.merge_failed(DownloadError(BAD))
    assert not source.merge_failed(DownloadError("ERROR: HTTP Error 404: Not Found"))
    assert source._exit_code(BAD) == "3436169992 (0xCCCFCB08)"
    assert source._exit_code("code 1") == "1"


def _parts(tmp_path, stem):
    v, a = tmp_path / f"{stem}.f100.mp4", tmp_path / f"{stem}.f200.m4a"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=5:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(v)], check=True, timeout=60)
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(a)],
                   check=True, timeout=60)
    return v, a


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")
def test_our_own_join_works_and_a_broken_part_keeps_ffmpegs_message(tmp_path):
    v, a = _parts(tmp_path, "bilibili_1")
    joined, _ = source.merge_parts(tmp_path, "bilibili_1")
    assert joined and (tmp_path / "bilibili_1.mp4").stat().st_size > 0 and not v.exists() and not a.exists()

    _parts(tmp_path, "bilibili_2")
    (tmp_path / "bilibili_2.f200.m4a").write_bytes(b"not audio at all")
    joined, said = source.merge_parts(tmp_path, "bilibili_2")
    assert not joined and said.startswith("exit ") and len(said) > 10  # FFmpeg's own last lines


def test_yt_dlp_is_asked_once_more_then_the_job_error_names_the_cause(tmp_path, monkeypatch):
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            calls.append(url)
            raise DownloadError(BAD)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(source, "merge_parts", lambda d, s: (False, "exit 1: Invalid data found when processing input"))
    with pytest.raises(source.SourceError) as err:
        source._retry_merge("https://www.bilibili.tv/th/video/1", {}, tmp_path, "bilibili_1", DownloadError(BAD))
    assert len(calls) == 1  # the one extra try (the first failure happened before)
    assert err.value.code == source.SourceErrorCode.DOWNLOADER_ERROR
    assert "0xCCCFCB08" in err.value.detail and "Invalid data found" in err.value.detail

    monkeypatch.setattr(source, "merge_parts", lambda d, s: (True, ""))
    source._retry_merge("https://www.bilibili.tv/th/video/1", {}, tmp_path, "bilibili_1", DownloadError(BAD))  # joined


def test_the_second_try_succeeding_needs_nothing_else(tmp_path, monkeypatch):
    class OkYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            return {}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", OkYDL)
    monkeypatch.setattr(source, "merge_parts", lambda d, s: pytest.fail("not needed"))
    source._retry_merge("https://www.bilibili.tv/th/video/1", {}, tmp_path, "bilibili_1", DownloadError(BAD))
