"""Server-side checks of an uploaded clip (FR-06, G3-03, G3-05 auto mode).

ffprobe only reads the container/stream headers. If ffprobe is not installed the checks are
recorded as skipped, and a clip with skipped checks is never auto-approved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

TARGET = (1080, 1920)  # 9:16 render size (Template v2)


def ffprobe_path() -> str | None:
    return os.environ.get("FFPROBE") or shutil.which("ffprobe")


def check(path: Path, *, reported_duration_ms: int, clip_min_s: int, clip_max_s: int) -> dict:
    exe = ffprobe_path()
    if not exe:
        return {"status": "skipped", "reason": "ffprobe_not_available", "checks": []}
    proc = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        return {"status": "failed", "reason": "not_a_media_file", "checks": [
            {"name": "readable", "ok": False, "detail": (proc.stderr or "").strip()[:200]}]}
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or 0)
    size = (int(video.get("width", 0)), int(video.get("height", 0))) if video else (0, 0)
    checks = [
        {"name": "video_stream", "ok": video is not None, "detail": video.get("codec_name") if video else None},
        {"name": "size_9_16", "ok": size == TARGET, "detail": f"{size[0]}x{size[1]}"},
        {"name": "audio_stream", "ok": audio is not None, "detail": audio.get("codec_name") if audio else None},
        {"name": "duration_in_range", "ok": clip_min_s - 1 <= duration <= clip_max_s + 1, "detail": round(duration, 2)},
        {"name": "duration_matches_report", "ok": abs(duration * 1000 - reported_duration_ms) <= 500,
         "detail": f"{round(duration * 1000)} vs {reported_duration_ms} ms"},
    ]
    return {"status": "passed" if all(c["ok"] for c in checks) else "failed", "checks": checks}
