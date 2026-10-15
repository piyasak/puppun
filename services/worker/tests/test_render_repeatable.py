"""A remake of the same segment is the same file (PRD section F/H: approvals and schedule items are
bound to the render sha256; a different hash parks the posts)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from clipflow_worker.media import binary, probe
from clipflow_worker.render import ClipText, RenderLimits, Template, render_clip
from clipflow_worker.segments import Cue


def _source(path: Path) -> Path:
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                    "-metadata", "creation_time=2026-01-02T03:04:05Z", "-metadata", "location=+13.75+100.50/",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


TEXT = ClipText("ทดสอบ ตอนที่ 1/2", "ติดตามตอนต่อไป", [Cue(0.5, 2.0, "สวัสดีครับ")])


def test_same_segment_renders_to_the_same_bytes_on_any_cpu(tmp_path):
    src = _source(tmp_path / "src.mp4")
    first = render_clip(src, 1.5, 4.0, TEXT, tmp_path / "a" / "clip.mp4", Template(), RenderLimits(threads=1))
    again = render_clip(src, 1.5, 4.0, TEXT, tmp_path / "b" / "clip.mp4", Template(), RenderLimits(threads=1))
    other_pc = render_clip(src, 1.5, 4.0, TEXT, tmp_path / "c" / "clip.mp4", Template(), RenderLimits(threads=3))
    assert first.sha256 == again.sha256 == other_pc.sha256


def test_source_metadata_is_not_carried_into_the_clip(tmp_path):
    src = _source(tmp_path / "src.mp4")
    result = render_clip(src, 0, 3.0, TEXT, tmp_path / "clip.mp4", Template(), RenderLimits(threads=1))
    tags = probe(result.path)["format"].get("tags", {})
    assert "creation_time" not in tags and "location" not in tags


def test_the_encoder_runs_the_same_on_every_cpu(tmp_path, monkeypatch):
    """What one CPU cannot show: x264 in cpu-independent mode with a fixed thread count, FFmpeg's
    SIMD held to SSE2 on x86-64 (12 CI runners, 5 CPU models: one file; without it AAC differed by
    CPU and x264 differed Intel/AMD and, on AVX-512, from one render to the next)."""
    import platform

    src = _source(tmp_path / "src.mp4")
    seen = []
    real_run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(cmd), real_run(cmd, **kw))[1])
    render_clip(src, 0, 2.0, TEXT, tmp_path / "clip.mp4", Template(), RenderLimits(threads=1))
    cmd = next(c for c in seen if "libx264" in c)
    assert cmd[cmd.index("-x264-params") + 1] == "cpu-independent=1" and cmd[cmd.index("-threads") + 1] == "4"
    if platform.machine().lower() in ("amd64", "x86_64"):
        assert cmd[cmd.index("-cpuflags") + 1] == "mmx+mmxext+sse+sse2+cmov"
