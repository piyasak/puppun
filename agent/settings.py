"""What the settings window does, without the window (PO 2026-10-10), so it can be tested.

- pair: send a pairing code from the web once; the server answers with this PC's own Agent token,
  which is stored encrypted for this Windows user (never shown, never typed)
- folders: where finished clips are kept (Q-33, at least 5 GB free for new jobs) and where the
  customer's own videos are (Q-17), both remembered in config.json
- start with Windows: a shortcut in the user's Startup folder that starts `connect`
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from agent import clips_folder
from agent.credentials import AgentConfig, load_config, save_config, save_token


class SettingsError(Exception):
    pass


@dataclass
class State:
    server: str | None
    username: str | None
    paired: bool
    clips_dir: str
    clips_free_gb: float
    media_dir: str | None
    autostart: bool
    show_screens: bool = False
    screens_control: bool = True
    max_parallel_posts: int = 1


def computer_name() -> str:
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "PC")[:40]


def load(data_dir: Path, startup_dir: Path | None = None) -> State:
    cfg = load_config(data_dir)
    # Not chosen yet: suggest Videos\punpun rather than the Agent's own data folder
    clips = Path(cfg.clips_dir) if cfg and cfg.clips_dir else clips_folder.suggested()
    return State(cfg.server if cfg else None, cfg.username if cfg else None, (data_dir / "token.bin").exists(),
                 str(clips), round(clips_folder.free_bytes(clips) / 1024**3, 1), cfg.media_dir if cfg else None,
                 autostart_on(startup_dir), bool(cfg and cfg.show_screens), bool(not cfg or cfg.screens_control),
                 cfg.max_parallel_posts if cfg else 1)


def pair(data_dir: Path, server: str, code: str, client_factory=None) -> dict:
    """Exchange a pairing code for this PC's Agent token and remember the server and username."""
    from agent.server_client import ServerClient, ServerError

    if not code.strip():
        raise SettingsError("ใส่รหัสเชื่อมต่อจากหน้า Agent บนเว็บ")
    try:
        client = (client_factory or ServerClient)(server)
        result = client.pair(code, computer_name())
    except ServerError as exc:
        raise SettingsError(exc.message) from None
    except (OSError, ValueError) as exc:
        raise SettingsError(f"ติดต่อ Server ไม่ได้ ({exc})") from None
    old = load_config(data_dir)
    save_config(data_dir, AgentConfig(client.base, result["username"], old.clips_dir if old else None,
                                      old.media_dir if old else None))
    save_token(data_dir, result["token"])  # encrypted for this Windows user (DPAPI)
    return {"username": result["username"], "environment": result["environment"]["name"]}


def save_folders(data_dir: Path, clips_dir: str, media_dir: str) -> tuple[Path, Path | None]:
    cfg = load_config(data_dir)
    if cfg is None:
        raise SettingsError("เชื่อมต่อบัญชีก่อน แล้วค่อยบันทึกโฟลเดอร์")
    try:
        clips = clips_folder.check(Path(clips_dir.strip().strip('"')))
    except clips_folder.FolderError as exc:
        raise SettingsError(f"โฟลเดอร์เก็บคลิป: {exc}") from None
    media = None
    if media_dir.strip():
        media = Path(media_dir.strip().strip('"')).expanduser()
        if not media.is_absolute() or not media.is_dir():
            raise SettingsError("โฟลเดอร์วิดีโอของฉัน: ไม่พบโฟลเดอร์นี้")
        media = media.resolve()
    old = clips_folder.current(data_dir)
    cfg.clips_dir, cfg.media_dir = str(clips), str(media) if media else None
    save_config(data_dir, cfg)
    if old != clips:
        clips_folder.move_jobs(old, clips)  # clips made before still post from the new folder
    return clips, media


def save_screens(data_dir: Path, show: bool, control: bool) -> None:
    """Phone screens on the PC while the Agent runs (PO 2026-10-10); takes effect at the next start."""
    cfg = load_config(data_dir)
    if cfg is None:
        raise SettingsError("เชื่อมต่อบัญชีก่อน แล้วค่อยบันทึก")
    cfg.show_screens, cfg.screens_control = show, control
    save_config(data_dir, cfg)


def save_posting(data_dir: Path, max_parallel: int) -> int:
    """Phones posting at the same time on this PC (PO 2026-10-23, default 1); takes effect at the next start."""
    from agent.credentials import parallel_posts

    cfg = load_config(data_dir)
    if cfg is None:
        raise SettingsError("เชื่อมต่อบัญชีก่อน แล้วค่อยบันทึก")
    cfg.max_parallel_posts = parallel_posts(max_parallel)
    save_config(data_dir, cfg)
    return cfg.max_parallel_posts


# --- start with Windows -------------------------------------------------------------------------

STARTUP_LINK = "punpun Agent.lnk"


def startup_folder() -> Path:
    from agent.setup_win import _powershell

    return Path(_powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8;[Environment]::GetFolderPath('Startup')", {}))


def autostart_on(startup_dir: Path | None = None) -> bool:
    try:
        return ((startup_dir or startup_folder()) / STARTUP_LINK).is_file()
    except OSError:
        return False


def set_autostart(on: bool, launcher: Path, startup_dir: Path | None = None) -> None:
    from agent.setup_win import make_shortcut

    lnk = (startup_dir or startup_folder()) / STARTUP_LINK
    if on:
        make_shortcut(lnk, launcher, Path.home(), minimized=True, icon=launcher.with_name("punpun.ico"))
    else:
        lnk.unlink(missing_ok=True)
