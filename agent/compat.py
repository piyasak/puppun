"""Supported combinations (D03, NF-10, T25): the Agent refuses to drive TikTok on anything else.

Only what was tested on the QA setup is listed. Adding a phone model, Android or TikTok version
means testing it first (G1-03 / G5-01) and adding it here in a new Agent version.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# (model, Android release, TikTok package, TikTok version) certified together.
PHONE_MATRIX = {
    ("25078PC3EG", "15", "com.ss.android.ugc.trill", "40.0.0"),
}
MIN_WINDOWS_BUILD = 22000  # Windows 11 (the QA PC); Windows 10 is not tested


@dataclass(frozen=True)
class Verdict:
    supported: bool
    reason: str | None = None


def check_phone(model: str | None, android: str | None, package: str | None, version: str | None) -> Verdict:
    key = (model or "", android or "", package or "", version or "")
    if key in PHONE_MATRIX:
        return Verdict(True)
    known = [m for m in PHONE_MATRIX if m[0] == key[0]]
    if not known:
        return Verdict(False, f"phone model {key[0] or '?'} is not tested yet")
    if not any(m[1] == key[1] for m in known):
        return Verdict(False, f"Android {key[1] or '?'} is not tested on {key[0]}")
    return Verdict(False, f"TikTok {key[3] or '?'} ({key[2] or '?'}) is not tested on {key[0]}")


def check_windows(system: str | None = None, build: int | None = None) -> Verdict:
    # sys.platform, never platform.system(): on Windows, Python 3.14 asks WMI for it and a stuck WMI hangs.
    system = system or {"win32": "Windows", "darwin": "Darwin"}.get(sys.platform, sys.platform.capitalize())
    if system != "Windows":
        return Verdict(False, f"{system} is not supported (Windows 11 only)")
    build = build if build is not None else (sys.getwindowsversion().build if sys.platform == "win32" else 0)
    if build < MIN_WINDOWS_BUILD:
        return Verdict(False, f"Windows build {build} is older than Windows 11")
    return Verdict(True)
