"""Agent installation identity and single-process lock (FR-14, T04).

- `installation_id` is generated once and kept in the Agent's data folder, so restarts and
  reconnects reuse the same registration on the server (T03). It identifies the install;
  it is not a secret and not proof of a particular machine (PRD §6).
- `ProcessLock` stops a second Agent process on the same install from running at all. The
  server's session fencing covers the case where two copies run anyway (copied folder).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "ClipFlowAgent"


def load_or_create_installation_id(data_dir: Path) -> str:
    path = data_dir / "installation_id"
    try:
        value = path.read_text(encoding="ascii").strip()
        uuid.UUID(value)
        return value
    except (FileNotFoundError, ValueError):
        pass
    data_dir.mkdir(parents=True, exist_ok=True)
    value = str(uuid.uuid4())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value, encoding="ascii")
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written id
    return value


class AlreadyRunning(Exception):
    pass


class ProcessLock:
    """Exclusive, non-blocking OS file lock; released automatically if the process dies."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "agent.lock"
        self._fh = None

    def acquire(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(f"another Agent process holds {self.path}") from None
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "ProcessLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
