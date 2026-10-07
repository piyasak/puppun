"""Customer-provided video files (PO request 2026-10-07, Q-17).

The customer downloads a video themselves and hands the file to the Agent, which
cuts and posts it like a linked source. Nothing is fetched from the network, so
the URL allowlist and SSRF guard do not apply; instead the file must be a regular
file, within the size cap, and ffprobe must find a video stream with a duration.
The file extension is not trusted. The source ID is the file's SHA-256, so the same
file always maps to the same source and the job keeps an audit trail of exactly
which bytes were used. Only the file name is recorded, never the full local path
(it can contain the Windows user name).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from clipflow_worker.media import binary
from clipflow_worker.source import SourceError, SourceErrorCode, SourceInfo

DEFAULT_MAX_LOCAL_FILESIZE = 8 * 1024**3


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def inspect_local(path: Path, max_filesize: int = DEFAULT_MAX_LOCAL_FILESIZE) -> SourceInfo:
    if not path.exists():
        raise SourceError(SourceErrorCode.NOT_FOUND, f"file not found: {path.name}")
    if not path.is_file():
        raise SourceError(SourceErrorCode.UNSUPPORTED_FILE, f"not a regular file: {path.name}")
    size = path.stat().st_size
    if size > max_filesize:
        raise SourceError(SourceErrorCode.LIMIT_EXCEEDED, f"file is {size} bytes; limit {max_filesize}")
    result = subprocess.run(
        [binary("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        info = json.loads(result.stdout) if result.returncode == 0 else {}
    except json.JSONDecodeError:
        info = {}
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    duration = info.get("format", {}).get("duration")
    if video is None or duration is None:
        raise SourceError(SourceErrorCode.UNSUPPORTED_FILE, f"{path.name} is not a readable video file")
    return SourceInfo(
        platform="local",
        source_id=sha256_file(path),
        url="",
        title=path.stem,
        duration_s=int(float(duration)),
        uploader=None,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        license=None,
        extractor="local-file",
    )


def sidecar_captions(path: Path) -> Path | None:
    """`<video>.srt` next to the video, if the customer supplied one."""
    candidate = path.with_suffix(".srt")
    return candidate if candidate.is_file() else None
