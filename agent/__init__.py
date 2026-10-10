"""punpun Windows Agent."""

import sys
from pathlib import Path

SOURCE_VERSION = "0.3.4"  # 0.3.3 + phone screens on the PC (scrcpy, ordered by web names, view-only lock)


def _version() -> str:
    # A packaged build carries the release version stamped by tools/build_agent.py.
    if getattr(sys, "frozen", False):
        stamp = Path(sys.executable).with_name("version.txt")
        if stamp.exists():
            return stamp.read_text(encoding="ascii").strip()
    return SOURCE_VERSION


__version__ = _version()
