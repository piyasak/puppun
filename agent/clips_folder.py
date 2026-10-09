"""Where finished clips are kept on this PC (Q-33).

Clips are never uploaded: the server gets checks and a still, and the Agent later posts the file
from this folder. The folder is chosen at `login` (with a suggested default) and can be changed
with `set-folder`; it is remembered in the Agent's config. Installs from before Q-33 kept clips
under <data dir>/clips, which stays the fallback and is still searched when posting.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

MIN_FREE_BYTES = 5 * 1024**3  # below this no new job is claimed (a 5-minute 1080x1920 clip is ~100-200 MB)


class FolderError(Exception):
    pass


def suggested() -> Path:
    return Path.home() / "Videos" / "punpun"


def legacy(data_dir: Path) -> Path:
    return Path(data_dir) / "clips"


def current(data_dir: Path) -> Path:
    from agent.credentials import load_config

    cfg = load_config(Path(data_dir))
    return Path(cfg.clips_dir) if cfg and cfg.clips_dir else legacy(data_dir)


def search_order(data_dir: Path) -> list[Path]:
    """Where a clip may be when it is posted: the chosen folder, then the pre-Q-33 one."""
    out = [current(data_dir)]
    if legacy(data_dir) not in out:
        out.append(legacy(data_dir))
    return out


def check(folder: Path) -> Path:
    """The folder must be absolute, creatable and writable. Returns it resolved."""
    folder = Path(folder).expanduser()
    if not folder.is_absolute():
        raise FolderError("ใช้ path เต็ม เช่น D:\\punpun\\clips")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise FolderError(f"เขียนไฟล์ในโฟลเดอร์นี้ไม่ได้ ({exc.strerror or exc})") from None
    return folder.resolve()


def free_bytes(folder: Path) -> int:
    folder = Path(folder)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    return shutil.disk_usage(folder).free


def has_room(folder: Path) -> bool:
    return free_bytes(folder) >= MIN_FREE_BYTES


def move_jobs(old: Path, new: Path) -> int:
    """Move every job folder (<job id>/clip_NN.mp4) from old to new. Returns how many moved."""
    if not old.is_dir() or old.resolve() == new.resolve():
        return 0
    moved = 0
    for job in old.iterdir():
        if job.is_dir() and not (new / job.name).exists():
            shutil.move(str(job), str(new / job.name))
            moved += 1
    return moved
