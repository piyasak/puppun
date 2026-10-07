"""Source adapter around yt-dlp (FR-02, FR-03).

Validates that a URL belongs to a supported platform, reads metadata without
downloading, and downloads a size/duration-limited rendition. Every failure is
mapped to a distinct SourceErrorCode so the UI can tell "not found" from
"not accessible" from "downloader broke" (FR-03), and nothing retries forever.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError

from clipflow_worker.media import binary

PLATFORM_HOSTS = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
    "bilibili": {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "bilibili.tv", "www.bilibili.tv"},
}

# Proposed POC limits (Q-03 / D02 still open); enforced before any media download.
DEFAULT_MAX_DURATION_S = 60 * 60
DEFAULT_MAX_FILESIZE = 2 * 1024**3
DEFAULT_MAX_HEIGHT = 1080


class SourceErrorCode(StrEnum):
    UNSUPPORTED_URL = "UNSUPPORTED_URL"
    NOT_FOUND = "SOURCE_NOT_FOUND"
    NOT_ACCESSIBLE = "SOURCE_NOT_ACCESSIBLE"  # private, login, geo, age or membership restricted
    LIMIT_EXCEEDED = "SOURCE_LIMIT_EXCEEDED"
    DOWNLOADER_ERROR = "DOWNLOADER_ERROR"


class SourceError(Exception):
    def __init__(self, code: SourceErrorCode, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class SourceInfo:
    platform: str
    source_id: str
    url: str
    title: str
    duration_s: int | None
    uploader: str | None
    width: int | None
    height: int | None
    license: str | None
    language: str | None = None
    subtitle_langs: list[str] = field(default_factory=list)
    auto_caption_langs: list[str] = field(default_factory=list)
    extractor: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def classify_platform(url: str) -> str:
    """Return the platform for an allowed https URL, or raise UNSUPPORTED_URL."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise SourceError(SourceErrorCode.UNSUPPORTED_URL, "only https URLs are accepted")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise SourceError(SourceErrorCode.UNSUPPORTED_URL, "credentials or custom ports are not allowed")
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        raise SourceError(SourceErrorCode.UNSUPPORTED_URL, "IP address hosts are not allowed")
    except ValueError:
        pass
    for platform, hosts in PLATFORM_HOSTS.items():
        if host in hosts:
            return platform
    raise SourceError(SourceErrorCode.UNSUPPORTED_URL, f"host not supported: {host}")


_NOT_FOUND_MARKERS = ("video unavailable", "does not exist", "404", "not found", "has been removed")
_NOT_ACCESSIBLE_MARKERS = (
    "private video", "sign in", "login", "members-only", "age", "geo", "not available in your country",
    "premium", "copyright", "confirm you",
)


def _classify_download_error(exc: Exception) -> SourceError:
    message = str(exc).lower()
    if any(m in message for m in _NOT_ACCESSIBLE_MARKERS):
        return SourceError(SourceErrorCode.NOT_ACCESSIBLE, str(exc))
    if any(m in message for m in _NOT_FOUND_MARKERS):
        return SourceError(SourceErrorCode.NOT_FOUND, str(exc))
    if "unsupported url" in message:
        return SourceError(SourceErrorCode.UNSUPPORTED_URL, str(exc))
    return SourceError(SourceErrorCode.DOWNLOADER_ERROR, str(exc))


def _base_opts() -> dict:
    return {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 2,  # bounded: FR-03 forbids unlimited retry
        "fragment_retries": 2,
        "socket_timeout": 30,
        # YouTube needs a JS runtime for signature solving; Node is already a project dependency.
        "js_runtimes": {"node": {}},
    }


def assert_public_media_url(media_url: str) -> None:
    """SSRF guard for adapter-returned media URLs (NF-03): http(s) to public addresses only."""
    parts = urlsplit(media_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, "media URL has an unsupported scheme")
    try:
        addresses = {ai[4][0] for ai in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except socket.gaierror as exc:
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, f"media host does not resolve: {exc}") from exc
    for address in addresses:
        if not ipaddress.ip_address(address.split("%", 1)[0]).is_global:
            raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, "media URL resolves to a non-public address")


def _probe_duration(info: dict) -> int | None:
    """Read duration from the smallest stream header when the extractor does not report it."""
    candidates = [f for f in info.get("formats") or [] if f.get("url") and f.get("protocol", "https") in ("http", "https")]
    if not candidates:
        return None
    fmt = min(candidates, key=lambda f: f.get("filesize") or f.get("tbr") or float("inf"))
    assert_public_media_url(fmt["url"])
    headers = "".join(f"{k}: {v}\r\n" for k, v in (fmt.get("http_headers") or {}).items())
    cmd = [binary("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json"]
    if headers:
        cmd += ["-headers", headers]
    try:
        result = subprocess.run(cmd + [fmt["url"]], capture_output=True, text=True, timeout=60, check=True)
        return int(float(json.loads(result.stdout)["format"]["duration"]))
    except (subprocess.SubprocessError, KeyError, ValueError, OSError):
        return None


def inspect(url: str) -> SourceInfo:
    platform = classify_platform(url)
    try:
        with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    if info is None or info.get("_type") == "playlist":
        raise SourceError(SourceErrorCode.UNSUPPORTED_URL, "playlists are not supported; use one video URL")
    duration = info.get("duration") or _probe_duration(info)
    return SourceInfo(
        platform=platform,
        source_id=str(info.get("id")),
        url=info.get("webpage_url") or url,
        title=info.get("title") or "",
        duration_s=int(duration) if duration else None,
        language=info.get("language"),
        uploader=info.get("uploader"),
        width=info.get("width"),
        height=info.get("height"),
        license=info.get("license"),
        subtitle_langs=sorted((info.get("subtitles") or {}).keys()),
        # Original-language machine captions only; translated tracks are out of MVP scope (Q-01).
        auto_caption_langs=sorted(k for k in (info.get("automatic_captions") or {}) if k.endswith("-orig")),
        extractor=info.get("extractor_key") or "",
    )


def check_limits(info: SourceInfo, max_duration_s: int = DEFAULT_MAX_DURATION_S) -> None:
    if info.duration_s is None:
        raise SourceError(SourceErrorCode.LIMIT_EXCEEDED, "duration unknown; cannot reserve quota")
    if info.duration_s > max_duration_s:
        raise SourceError(
            SourceErrorCode.LIMIT_EXCEEDED, f"duration {info.duration_s}s exceeds limit {max_duration_s}s"
        )


def download(
    url: str,
    dest_dir: Path,
    *,
    max_duration_s: int = DEFAULT_MAX_DURATION_S,
    max_filesize: int = DEFAULT_MAX_FILESIZE,
    max_height: int = DEFAULT_MAX_HEIGHT,
    subtitle_langs: list[str] | None = None,
) -> tuple[SourceInfo, Path, list[Path]]:
    """Download one video (and its uploaded subtitles, never machine translations)."""
    info = inspect(url)
    check_limits(info, max_duration_s)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{info.platform}_{info.source_id}"
    opts = {
        **_base_opts(),
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b",
        "merge_output_format": "mp4",
        "max_filesize": max_filesize,
        "outtmpl": str(dest_dir / f"{stem}.%(ext)s"),
        "writesubtitles": True,
        "subtitleslangs": subtitle_langs or ["all", "-live_chat"],
        "subtitlesformat": "srt/vtt/best",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    video = dest_dir / f"{stem}.mp4"
    if not video.exists():
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, "download finished without an mp4 output")
    subs = sorted(p for p in dest_dir.glob(f"{stem}.*") if p.suffix in (".srt", ".vtt", ".ass"))
    return info, video, subs
