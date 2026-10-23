"""Source adapter around yt-dlp (FR-02, FR-03).

Validates that a URL belongs to a supported platform, reads metadata without
downloading, and downloads a size/duration-limited rendition. Every failure is
mapped to a distinct SourceErrorCode so the UI can tell "not found" from
"not accessible" from "downloader broke" (FR-03), and nothing retries forever.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import DownloadError

from clipflow_worker.media import binary
from clipflow_worker.netguard import BLOCKED_MESSAGE, BlockedAddress, check_url, public_only

PLATFORM_HOSTS = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
    "bilibili": {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "bilibili.tv", "www.bilibili.tv"},
}

# Source cap is a resource limit (E-17); D02 sets clip length, not source length.
# Enforced before any media download.
DEFAULT_MAX_DURATION_S = 4 * 60 * 60
DEFAULT_MAX_FILESIZE = 2 * 1024**3
DEFAULT_MAX_HEIGHT = 1080


class SourceErrorCode(StrEnum):
    UNSUPPORTED_URL = "UNSUPPORTED_URL"
    NOT_FOUND = "SOURCE_NOT_FOUND"
    NOT_ACCESSIBLE = "SOURCE_NOT_ACCESSIBLE"  # private, login, geo, age or membership restricted
    RATE_LIMITED = "SOURCE_RATE_LIMITED"  # platform bot check / 429: temporary, retry after a cool-down
    LIMIT_EXCEEDED = "SOURCE_LIMIT_EXCEEDED"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"  # customer-provided file is not a readable video
    BLOCKED_ADDRESS = "SOURCE_BLOCKED_ADDRESS"  # a download or redirect pointed at a non-public address (T08)
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


# Network/proxy failures are checked first: they say nothing about the source itself
# and must not be reported to the user as "video unavailable" or "private".
_NETWORK_MARKERS = (
    "proxy", "unable to connect", "timed out", "connection reset", "connection refused",
    "name resolution", "getaddrinfo", "network is unreachable", "ssl:",
)
# Temporary platform throttling. Checked before the "sign in" access markers because
# YouTube's bot check says "Sign in to confirm you’re not a bot" (curly apostrophe).
_RATE_LIMIT_MARKERS = ("not a bot", "too many requests", "http error 429", "rate limit", "rate-limit")
_NOT_FOUND_MARKERS = ("video unavailable", "does not exist", "http error 404", "not found", "has been removed")
# Phrases, not bare words: a bare "age" matched "page" and misreported a proxy error (P1, 2026-10-07).
_NOT_ACCESSIBLE_MARKERS = (
    "private video", "sign in", "login", "members-only", "age-restricted", "confirm your age",
    "inappropriate for some users", "geo-restricted", "geo restricted", "not available in your country",
    "premium", "copyright",
)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _classify_download_error(exc: Exception) -> SourceError:
    exc = _ANSI.sub("", str(exc))  # yt-dlp colours "ERROR:"; details are shown to users
    message = exc.lower()
    if BLOCKED_MESSAGE in message:  # before the network markers: this is a refusal, not an outage
        return SourceError(SourceErrorCode.BLOCKED_ADDRESS, "the source pointed to a private or internal address")
    if any(m in message for m in _NETWORK_MARKERS):
        return SourceError(SourceErrorCode.DOWNLOADER_ERROR, f"network error (retryable): {exc}")
    if any(m in message for m in _RATE_LIMIT_MARKERS):
        return SourceError(SourceErrorCode.RATE_LIMITED, str(exc))
    if any(m in message for m in _NOT_ACCESSIBLE_MARKERS):
        return SourceError(SourceErrorCode.NOT_ACCESSIBLE, str(exc))
    if any(m in message for m in _NOT_FOUND_MARKERS):
        return SourceError(SourceErrorCode.NOT_FOUND, str(exc))
    if "unsupported url" in message:
        return SourceError(SourceErrorCode.UNSUPPORTED_URL, str(exc))
    return SourceError(SourceErrorCode.DOWNLOADER_ERROR, str(exc))


def merge_failed(exc: Exception) -> bool:
    """yt-dlp downloaded the video and audio but FFmpeg did not join them (customer PC, 2026-10-19:
    "ffmpeg exited with code 3436169992")."""
    message = _ANSI.sub("", str(exc)).lower()
    return "ffmpeg exited with code" in message or "postprocessing:" in message


def _exit_code(message: str) -> str:
    """'... code 3436169992' -> '3436169992 (0xCCCFCB08)': Windows crash codes read better in hex."""
    m = re.search(r"code (-?\d+)", message)
    if not m:
        return "?"
    code = int(m.group(1))
    return f"{code} (0x{code & 0xFFFFFFFF:08X})" if abs(code) > 255 else str(code)


def _parts(dest_dir: Path, stem: str) -> list[Path]:
    """The separate video and audio files yt-dlp keeps when the merge fails (stem.f<format>.<ext>)."""
    return sorted(p for p in dest_dir.glob(f"{stem}.f*.*") if p.suffix not in (".part", ".ytdl") and p.is_file())


def merge_parts(dest_dir: Path, stem: str, run=subprocess.run, timeout_s: float = 1800) -> tuple[bool, str]:
    """Join the kept parts with our own FFmpeg call, so its own words are kept when it fails.
    Returns (joined, the last lines FFmpeg wrote)."""
    from clipflow_worker.media import binary

    parts = _parts(dest_dir, stem)
    if len(parts) < 2:
        return False, f"no video and audio parts to join ({len(parts)} found)"
    out = dest_dir / f"{stem}.mp4"
    args = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
    for part in parts[:2]:
        args += ["-i", str(part)]
    args += ["-map", "0", "-map", "1", "-c", "copy", "-movflags", "+faststart", str(out)]
    try:
        done = run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"FFmpeg could not run: {type(exc).__name__}: {exc}"[:300]
    lines = [ln.strip() for ln in (done.stderr or "").splitlines() if ln.strip()]
    tail = " | ".join(lines[-3:])[:300]
    if done.returncode == 0 and out.is_file() and out.stat().st_size > 0:
        for part in parts[:2]:
            part.unlink(missing_ok=True)
        return True, tail
    return False, f"exit {_exit_code(f'code {done.returncode}')}: {tail or 'no message'}"


def _retry_merge(url: str, opts: dict, dest_dir: Path, stem: str, first: DownloadError) -> None:
    """PO 2026-10-23: when FFmpeg fails joining video and audio, try once more (the parts are kept, so only the
    join runs again), then join them ourselves to keep FFmpeg's own message. Raises with that message."""
    try:
        with public_only(), yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        return
    except DownloadError as exc:
        if not merge_failed(exc):
            raise _classify_download_error(exc) from exc
        second = exc
    joined, said = merge_parts(dest_dir, stem)
    if joined:
        return
    raise SourceError(SourceErrorCode.DOWNLOADER_ERROR,
                      f"FFmpeg joined the video and audio 3 times and failed (yt-dlp exit "
                      f"{_exit_code(str(first))}, again {_exit_code(str(second))}); FFmpeg said: {said}") from second


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
    try:
        check_url(media_url)
    except BlockedAddress as exc:
        raise SourceError(SourceErrorCode.BLOCKED_ADDRESS, "media URL is not a public http(s) address") from exc
    except socket.gaierror as exc:
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, f"media host does not resolve: {exc}") from exc


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


def format_options(max_short_side: int = DEFAULT_MAX_HEIGHT) -> dict:
    """Best video+audio whose *shorter* side is at most `max_short_side`.

    Filtering on height (`height<=1080`) picked 480x852 for vertical 720x1280 and
    1080x1920 sources, which were then upscaled to 1080x1920 (P1, 2026-10-07).
    yt-dlp's `res` is the smaller dimension, so this works for both orientations.
    """
    return {"format": "bv*+ba/b", "format_sort": [f"res:{max_short_side}"]}


def inspect(url: str) -> SourceInfo:
    platform = classify_platform(url)
    try:
        with public_only(), yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    if info is None or info.get("_type") == "playlist":
        raise SourceError(SourceErrorCode.UNSUPPORTED_URL, "playlists are not supported; use one video URL")
    with public_only():
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
        **format_options(max_height),
        "merge_output_format": "mp4",
        "max_filesize": max_filesize,
        "outtmpl": str(dest_dir / f"{stem}.%(ext)s"),
        "writesubtitles": True,
        "subtitleslangs": subtitle_langs or ["all", "-live_chat"],
        "subtitlesformat": "srt/vtt/best",
    }
    try:
        with public_only(), yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        if not merge_failed(exc):
            raise _classify_download_error(exc) from exc
        _retry_merge(url, opts, dest_dir, stem, exc)
    video = dest_dir / f"{stem}.mp4"
    if not video.exists():
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, "download finished without an mp4 output")
    subs = sorted(p for p in dest_dir.glob(f"{stem}.*") if p.suffix in (".srt", ".vtt", ".ass"))
    return info, video, subs
