"""punpun Windows Agent."""

import sys
from pathlib import Path

SOURCE_VERSION = "0.3.3"  # 0.3.2 + find moved clip files by hash, remake on a job reset (Q-38)


def _version() -> str:
    # A packaged build carries the release version stamped by tools/build_agent.py.
    if getattr(sys, "frozen", False):
        stamp = Path(sys.executable).with_name("version.txt")
        if stamp.exists():
            return stamp.read_text(encoding="ascii").strip()
    return SOURCE_VERSION


__version__ = _version()
