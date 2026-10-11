"""punpun Windows Agent."""

import sys
from pathlib import Path

SOURCE_VERSION = "0.5.3"  # 0.5.2 + Thai keyboard: reported per phone, live post stops without it, installed on request (Q-44)


# A packaged build (tools/build_agent.py): Nuitka-compiled from 0.4.0 (`__compiled__` exists in
# compiled modules), PyInstaller before that (sys.frozen). adb, scrcpy and version.txt sit next to the exe.
_COMPILED = "__compiled__" in globals()


def packaged() -> bool:
    return _COMPILED or bool(getattr(sys, "frozen", False))


def _version() -> str:
    # A packaged build carries the release version stamped by tools/build_agent.py.
    if packaged():
        stamp = Path(sys.executable).with_name("version.txt")
        if stamp.exists():
            return stamp.read_text(encoding="ascii").strip()
    return SOURCE_VERSION


__version__ = _version()
