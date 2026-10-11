r"""The videos folder, as the web shows it when a job is made (PO 2026-10-11).

    <videos folder>\
        เรื่องเต็ม.mp4            full videos at the top: the Agent cuts them by the job's settings
        เรื่องA\EP01.mp4 EP02.mp4  each sub-folder: clips already cut, sent as they are, in EP order

Every LIBRARY_EVERY_S the Agent lists names and sizes (never paths, never the files) and reports them
when something changed, or at least every RESEND_S. Only servers with the "video_library" feature
take the report.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi")
CLIP_EXTENSIONS = (".mp4",)  # clips already cut are shared into TikTok as video/mp4
LIBRARY_EVERY_S = 60.0
RESEND_S = 600.0


def natural(name: str) -> list:
    """EP2 before EP10: digits compare as numbers."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def clips_in(folder: Path) -> list[Path]:
    """The clips of one folder of clips already cut, in EP order."""
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in CLIP_EXTENSIONS
             and not p.name.startswith(".")]
    return sorted(files, key=lambda p: natural(p.name))


def scan(media_dir: Path) -> dict:
    videos, sets = [], []
    if not media_dir.is_dir():
        return {"videos": videos, "sets": sets}
    for entry in sorted(media_dir.iterdir(), key=lambda p: natural(p.name)):
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
                st = entry.stat()
                videos.append({"name": entry.name, "size_bytes": st.st_size,
                               "modified_at": datetime.fromtimestamp(st.st_mtime, UTC).isoformat()})
            elif entry.is_dir():
                clips = clips_in(entry)
                if clips:
                    sets.append({"folder": entry.name, "clips": [c.name for c in clips],
                                 "size_bytes": sum(c.stat().st_size for c in clips)})
        except OSError:
            continue  # a file being copied or locked: it shows up on the next scan
    return {"videos": videos, "sets": sets}


class LibraryWorker:
    def __init__(self, media_dir: Path, log=print, every_s: float = LIBRARY_EVERY_S):
        self.media_dir, self.log, self.every_s = Path(media_dir), log, every_s
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: tuple[str, float] | None = None

    def start(self, client, get_session) -> None:
        self._thread = threading.Thread(target=self._loop, args=(client, get_session), daemon=True,
                                        name="clipflow-library")
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout_s)

    def _loop(self, client, get_session) -> None:
        while not self._halt.is_set():
            try:
                self.report_once(client, get_session())
            except Exception as exc:  # noqa: BLE001 - the list is a convenience; never stop the Agent for it
                self.log(f"รายการวิดีโอ: ส่งไม่ได้ชั่วคราว ({exc})")
            self._halt.wait(self.every_s)

    def report_once(self, client, session) -> bool:
        """Report when changed (or every RESEND_S). Returns whether a report was sent."""
        if "video_library" not in session.features:
            return False
        library = scan(self.media_dir)
        digest = hashlib.sha256(json.dumps(library, sort_keys=True).encode()).hexdigest()
        if self._last and self._last[0] == digest and time.monotonic() - self._last[1] < RESEND_S:
            return False
        client.report_library(session, library)
        self._last = (digest, time.monotonic())
        return True
