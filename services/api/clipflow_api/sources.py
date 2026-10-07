"""Server-side source validation at job creation (FR-02, NF-03).

Same allowlist as the Agent's downloader (`clipflow_worker.source.classify_platform`; a parity
test keeps them in step). The server never fetches the URL: the Agent downloads on the
customer's machine (Q-15) and applies the redirect/media-URL SSRF guard there.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from .errors import ApiError

PLATFORM_HOSTS = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"},
    "bilibili": {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "bilibili.tv", "www.bilibili.tv"},
}
FILE_NAME_RE = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,200}$")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi")


def unsupported(reason: str) -> ApiError:
    return ApiError(422, "UNSUPPORTED_URL", "ลิงก์นี้ใช้ไม่ได้: รองรับเฉพาะ YouTube และ Bilibili แบบ https", {"reason": reason})


def classify_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise unsupported("https_only")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise unsupported("credentials_or_port")
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        raise unsupported("ip_host")
    except ValueError:
        pass
    for platform, hosts in PLATFORM_HOSTS.items():
        if host in hosts:
            return platform
    raise unsupported("host_not_allowed")


def check_file_label(label: str) -> str:
    """A customer file on the Agent machine is referenced by name only, never a full path (Q-17)."""
    label = label.strip()
    if not FILE_NAME_RE.match(label) or label in (".", ".."):
        raise ApiError(422, "UNSUPPORTED_FILE", "ระบุเฉพาะชื่อไฟล์ ไม่ต้องใส่ path")
    if not label.lower().endswith(VIDEO_EXTENSIONS):
        raise ApiError(422, "UNSUPPORTED_FILE", "รองรับไฟล์วิดีโอ .mp4 .mkv .mov .webm .m4v .avi")
    return label
