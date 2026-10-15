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
