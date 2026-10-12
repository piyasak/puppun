"""FFmpeg for cutting clips, installed on request (PO 2026-10-12).

The Agent does not carry FFmpeg. When it is missing (no FFMPEG_DIR, not on PATH, no winget copy),
"ติดตั้ง FFmpeg" in the settings window (or `agent.cli ffmpeg`) downloads Gyan's Windows build at one
fixed version, accepts it only if its SHA-256 is the one checked here, and puts ffmpeg.exe, ffprobe.exe
and FFmpeg's licence in <LOCALAPPDATA>/ClipFlowAgent/ffmpeg, where `clipflow_worker.media.binary` looks.

The build is GPL (libx264, libass are needed for the 9:16 render with subtitles). It runs as a separate
program; its licence travels with it and its source is at https://ffmpeg.org (and the build's page).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from agent import net

VERSION = "9.0.2"
ZIP_URL = f"https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/ffmpeg-{VERSION}-essentials_build.zip"
ZIP_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"  # checked 2026-10-12, 114,768,076 bytes
ZIP_MAX_BYTES = 300_000_000
INSIDE = f"ffmpeg-{VERSION}-essentials_build"
FILES = {f"{INSIDE}/bin/ffmpeg.exe": "ffmpeg.exe", f"{INSIDE}/bin/ffprobe.exe": "ffprobe.exe",
         f"{INSIDE}/LICENSE": "LICENSE.txt", f"{INSIDE}/README.txt": "README.txt"}


class FfmpegError(Exception):
    pass


def folder() -> Path:
    """Where the Agent installs FFmpeg (also searched by clipflow_worker.media.binary)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "ClipFlowAgent" / "ffmpeg"


def found() -> str | None:
    """The ffmpeg the Agent would use, or None."""
    from clipflow_worker.media import binary

    try:
        binary("ffprobe")
        return binary("ffmpeg")
    except FileNotFoundError:
        return None


def _download(dest: Path, opener, progress) -> None:
    digest, size = hashlib.sha256(), 0
    try:
        with opener(ZIP_URL, timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0) if getattr(resp, "headers", None) else 0
            while block := resp.read(1024 * 1024):
                size += len(block)
                if size > ZIP_MAX_BYTES:
                    raise FfmpegError("ไฟล์ FFmpeg ใหญ่ผิดปกติ จึงไม่ติดตั้ง")
                digest.update(block)
                out.write(block)
                if total and progress:
                    progress(size, total)
    except OSError as exc:
        raise FfmpegError(f"ดาวน์โหลด FFmpeg ไม่ได้: {exc}") from None
    if digest.hexdigest() != ZIP_SHA256:
        raise FfmpegError("ไฟล์ FFmpeg ที่ดาวน์โหลดมาไม่ตรงกับไฟล์ที่ตรวจไว้ จึงไม่ติดตั้ง")


def _move_into_place(staging: Path, target: Path, tries: int = 10, wait_s: float = 1.0, sleep=time.sleep) -> None:
    """Packaged Agent, 2026-10-12: renaming the folder right after the exes were written and run failed with
    "Access is denied" (antivirus still scanning them); it worked a moment later. So try for a while, then
    copy file by file."""
    shutil.rmtree(target, ignore_errors=True)
    for _ in range(tries):
        try:
            staging.replace(target)
            return
        except PermissionError:
            sleep(wait_s)
    target.mkdir(parents=True, exist_ok=True)
    for path in staging.iterdir():
        shutil.copy2(path, target / path.name)


def install(opener=net.urlopen, progress=None, run=subprocess.run) -> str:
    """Download, check and install. Returns 'present' or 'installed'; raises FfmpegError."""
    if found():
        return "present"
    target = folder()
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.parent / "ffmpeg-download.part"
    staging = target.parent / "ffmpeg.new"
    try:
        _download(part, opener, progress)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        with zipfile.ZipFile(part) as zf:  # only the named files, never paths taken from the archive
            for inside, name in FILES.items():
                try:
                    (staging / name).write_bytes(zf.read(inside))
                except KeyError:
                    raise FfmpegError(f"ไฟล์ FFmpeg ไม่ครบ ({name})") from None
        probe = run([str(staging / "ffmpeg.exe"), "-hide_banner", "-version"], capture_output=True, text=True, timeout=60)
        if probe.returncode != 0 or "--enable-libass" not in probe.stdout or "--enable-libx264" not in probe.stdout:
            raise FfmpegError("FFmpeg ที่ติดตั้งเปิดไม่ได้หรือไม่มีส่วนที่ต้องใช้ (libx264, libass)")
        _move_into_place(staging, target)
    except zipfile.BadZipFile:
        raise FfmpegError("ไฟล์ FFmpeg เสีย ลองใหม่อีกครั้ง") from None
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    return "installed"
