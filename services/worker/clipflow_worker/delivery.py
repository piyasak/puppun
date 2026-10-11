"""What the Agent sends instead of the clip file (Q-33): checks and a small still image.

The finished clip stays on the customer's PC (the folder chosen in the Agent) and is posted from
there; the server only receives the hash, these checks and one JPEG of three frames for the review
page. `check_clip` applies the same rules as the server's `clipflow_api.mediacheck` (kept in step by
tests/unit/test_delivery.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .media import binary

TARGET = (1080, 1920)  # 9:16 render size (Template v2)
PREVIEW_MAX_BYTES = 2 * 1024 * 1024


def check_clip(path: Path, *, reported_duration_ms: int, clip_min_s: float, clip_max_s: float) -> dict:
    try:
        exe = binary("ffprobe")
    except FileNotFoundError:
        return {"status": "skipped", "reason": "ffprobe_not_available", "checks": []}
    proc = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return {"status": "failed", "reason": "not_a_media_file", "checks": [
            {"name": "readable", "ok": False, "detail": "not a readable video file"}]}
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


PRECUT_MAX_S = 600  # TikTok's longest upload from the phone app


def probe_duration_s(path: Path) -> float:
    """Length of a video file in seconds (0 when it cannot be read)."""
    proc = subprocess.run([binary("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                           "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=60)
    try:
        return float(proc.stdout.strip() or 0)
    except ValueError:
        return 0.0


def check_ready_clip(path: Path) -> dict:
    """Checks for a clip that was already cut (PO 2026-10-11): it is posted as it is, so it must be a
    readable .mp4 with picture and sound, 1 s to 10 minutes. Its size is reported, not required."""
    try:
        exe = binary("ffprobe")
    except FileNotFoundError:
        return {"status": "skipped", "reason": "ffprobe_not_available", "checks": []}
    proc = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return {"status": "failed", "reason": "not_a_media_file", "checks": [
            {"name": "readable", "ok": False, "detail": "not a readable video file"}]}
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or 0)
    detail = f"{video.get('codec_name')} {video.get('width')}x{video.get('height')}" if video else None
    checks = [
        {"name": "mp4_file", "ok": path.suffix.lower() == ".mp4", "detail": path.suffix.lower()},
        {"name": "video_stream", "ok": video is not None, "detail": detail},
        {"name": "audio_stream", "ok": audio is not None, "detail": audio.get("codec_name") if audio else None},
        {"name": "duration_up_to_10_min", "ok": 1 <= duration <= PRECUT_MAX_S, "detail": round(duration, 2)},
    ]
    return {"status": "passed" if all(c["ok"] for c in checks) else "failed", "checks": checks}


def contact_sheet(path: Path, out: Path, duration_s: float) -> Path:
    """One JPEG with three frames side by side (at 15 %, 50 % and 85 %), 810x480, a few dozen KB."""
    start = max(0.0, duration_s * 0.15)
    every = max(duration_s * 0.35, 0.1)
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path),
                    "-vf", f"fps=1/{every:.3f},scale=270:480,tile=3x1", "-frames:v", "1", "-q:v", "5", str(out)],
                   check=True, capture_output=True, timeout=120)
    if out.stat().st_size > PREVIEW_MAX_BYTES:
        raise ValueError("preview image larger than expected")
    return out
