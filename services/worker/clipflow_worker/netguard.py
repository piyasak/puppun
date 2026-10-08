"""Connection-time SSRF guard for source downloads (NF-03, T08, G3-01).

An allowlisted first URL is not enough: the platform page, the media URLs it returns and every
HTTP redirect can point anywhere (PRD §E). Inside `public_only()` every host name resolved by
this thread must resolve only to public (globally routable) addresses, otherwise the lookup fails
before any connection is made. That covers yt-dlp's own HTTP stack and requests/urllib3, which
all resolve through `socket.getaddrinfo`, including each redirect hop.

The guard is per thread: the Agent keeps talking to its own server (which may be 127.0.0.1 in
development) from other code paths and threads while a download runs.

Not covered here: programs started as subprocesses (ffmpeg) resolve names themselves, so media
URLs handed to ffmpeg are checked with `check_url` first (see poc.download_range). A redirect
followed inside ffmpeg after that check is a known gap (E-38).
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
from urllib.parse import urlsplit

BLOCKED_MESSAGE = "blocked: resolves to a non-public address"

_state = threading.local()
_real_getaddrinfo = socket.getaddrinfo
_installed = False
_install_lock = threading.Lock()


class BlockedAddress(OSError):
    """A source download tried to reach a private, loopback, link-local or reserved address."""

    def __init__(self, host: str):
        super().__init__(f"{BLOCKED_MESSAGE} ({host})")
        self.host = host


def _is_public(address: str) -> bool:
    return ipaddress.ip_address(address.split("%", 1)[0]).is_global


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    results = _real_getaddrinfo(host, port, *args, **kwargs)
    allow = getattr(_state, "allow", None)
    if allow is not None:
        for _family, _type, _proto, _canon, sockaddr in results:
            if not allow(str(host), port, sockaddr[0]):
                raise BlockedAddress(str(host))
    return results


def _install() -> None:
    global _installed
    with _install_lock:
        if not _installed:
            socket.getaddrinfo = _guarded_getaddrinfo
            _installed = True


def default_allow(host: str, port, address: str) -> bool:
    return _is_public(address)


@contextlib.contextmanager
def public_only(allow=default_allow):
    """Within this block, this thread may only resolve names to addresses `allow` accepts.

    `allow(host, port, address)` exists for tests; production uses public addresses only.
    """
    _install()
    previous = getattr(_state, "allow", None)
    _state.allow = allow
    try:
        yield
    finally:
        _state.allow = previous


def check_url(url: str) -> None:
    """Resolve a URL's host now (inside the guard, if active) and refuse non-public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedAddress(parts.hostname or url[:40])
    allow = getattr(_state, "allow", None) or default_allow
    for *_rest, sockaddr in _real_getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)):
        if not allow(parts.hostname, parts.port, sockaddr[0]):
            raise BlockedAddress(parts.hostname)
