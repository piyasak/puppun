"""Q-33: what the Agent sends instead of the clip file — checks (same rules as the server) and a still."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services" / "worker"), str(ROOT / "services" / "api")]

from clipflow_api import mediacheck  # noqa: E402
from clipflow_worker import delivery  # noqa: E402
from clipflow_worker.media import binary  # noqa: E402


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("delivery") / "clip.mp4"
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=25:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


def test_agent_checks_match_the_server_rules(clip, monkeypatch):
    monkeypatch.setenv("FFPROBE", binary("ffprobe"))
    for lo, hi, reported in ((5, 7, 6000), (10, 20, 6000), (5, 7, 9000)):
        agent = delivery.check_clip(clip, reported_duration_ms=reported, clip_min_s=lo, clip_max_s=hi)
        server = mediacheck.check(clip, reported_duration_ms=reported, clip_min_s=lo, clip_max_s=hi)
        assert agent == server
    assert delivery.check_clip(clip, reported_duration_ms=6000, clip_min_s=5, clip_max_s=7)["status"] == "passed"


def test_not_a_video_fails_without_paths(tmp_path):
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"not a video")
    result = delivery.check_clip(junk, reported_duration_ms=6000, clip_min_s=5, clip_max_s=7)
    assert result["status"] == "failed" and str(tmp_path) not in str(result)


def test_contact_sheet_is_one_small_jpeg_of_three_frames(clip, tmp_path):
    out = delivery.contact_sheet(clip, tmp_path / "preview.jpg", 6.0)
    data = out.read_bytes()
    assert data[:3] == b"\xff\xd8\xff" and len(data) < 200_000
    probe = subprocess.run([binary("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert probe.stdout.strip() == "810,480"
