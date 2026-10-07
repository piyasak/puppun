"""Locate media binaries and probe rendered files (FR-06)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe: FFMPEG_DIR env, then PATH, then the winget links folder."""
    env_dir = os.environ.get("FFMPEG_DIR")
    candidates = [Path(env_dir) / f"{name}.exe", Path(env_dir) / name] if env_dir else []
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe")
    for candidate in candidates:
        if candidate.exists():
            # winget installs symlinks; yt-dlp needs the real folder holding ffmpeg+ffprobe.
            return str(candidate.resolve())
    raise FileNotFoundError(f"{name} not found; install FFmpeg or set FFMPEG_DIR")


def ensure_on_path() -> str:
    """Put the ffmpeg folder on PATH for this process.

    yt-dlp's partial-download check (FFmpegFD.available) looks only at PATH and
    ignores the ffmpeg_location option, so range downloads fail without this.
    """
    folder = str(Path(binary("ffmpeg")).parent)
    if folder not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return folder


def duration_gaps(info: dict, expected_s: float, tolerance_s: float) -> list[str]:
    """Compare a probe result's container, video and audio durations with the expected length.

    A truncated download can still be a valid, playable file (P1 found a 33 s file
    for a 231 s range with no error from yt-dlp), so length must be checked explicitly.
    """
    problems = []
    measured = {"container": info.get("format", {}).get("duration")}
    for stream in info.get("streams", []):
        if stream.get("codec_type") in ("video", "audio") and stream.get("duration"):
            measured.setdefault(stream["codec_type"], stream["duration"])
    for name, value in measured.items():
        if value is None:
            problems.append(f"{name} duration unknown")
        elif abs(float(value) - expected_s) > tolerance_s:
            problems.append(f"{name} duration {float(value):.2f}s, expected {expected_s:.2f}s")
    return problems


def probe(path: Path) -> dict:
    result = subprocess.run(
        [binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(result.stdout)
