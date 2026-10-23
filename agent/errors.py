"""What the server and the local log are told about an unexpected error on this PC (PO 2026-10-23).

Before 0.10.1 a failed job only said "AGENT_ERROR: FileNotFoundError", and job errors were printed to the
Agent window only, so the missing file could not be found from the web or the log. Now the server gets the
type, the message and the name of the file involved (never the folders above it under the user's profile),
and agent.log gets the whole traceback.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("punpun.agent")
MAX_LEN = 300


def _hide_home(text: str) -> str:
    home = os.path.expanduser("~")
    if home and home != "~":
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.IGNORECASE)
    return re.sub(r"(?i)[a-z]:\\users\\[^\\/\s'\"]+", "%USERPROFILE%", text)


def summary(exc: BaseException) -> str:
    """'FileNotFoundError: [Errno 2] No such file or directory: ffprobe.exe' (one line, at most 300 chars)."""
    name = type(exc).__name__
    if isinstance(exc, OSError) and (exc.strerror or exc.filename):
        parts = [f"[Errno {exc.errno}]" if exc.errno is not None else "", exc.strerror or ""]
        if exc.filename:
            parts.append(f"{Path(str(exc.filename)).name or exc.filename}")
        text = " ".join(p for p in parts if p)
    else:
        text = str(exc)
    line = _hide_home(f"{name}: {text}" if text else name).replace("\n", " ").strip()
    return line[:MAX_LEN]


def record(where: str, exc: BaseException) -> str:
    """Write the traceback to agent.log and return the summary for the server."""
    log.error("%s: %s", where, summary(exc), exc_info=(type(exc), exc, exc.__traceback__))
    return summary(exc)
