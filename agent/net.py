"""HTTPS for the Agent: certificates checked against Windows' roots and certifi's (2026-10-12).

A packaged Agent on a customer PC failed to download FFmpeg from GitHub with CERTIFICATE_VERIFY_FAILED
("unable to get local issuer certificate"): Python only sees the root certificates Windows has already
stored, and Windows fetches missing roots only when its own programs need them. certifi (Mozilla's roots,
shipped with the Agent through yt-dlp) is added, so verification stays on and works on a fresh PC.
"""

from __future__ import annotations

import functools
import ssl
import urllib.request


@functools.cache
def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()  # verification on, hostname checked, Windows' stored roots
    try:
        import certifi

        ctx.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass  # Windows' roots only, as before
    return ctx


def urlopen(request, timeout: float):
    """urllib.request.urlopen with the Agent's certificate roots (same arguments as used here)."""
    return urllib.request.urlopen(request, timeout=timeout, context=context())
