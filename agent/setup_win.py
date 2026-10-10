"""Double-click setup for Windows (E-50): punpun-agent-setup-<version>.exe.

One file a customer downloads and opens. It carries the Agent bundle (tools/build_agent.py) and its
SHA-256, and per Windows user, with no admin rights:

1. installs or updates the Agent through `agent.updater.install` (same checks as `install`: bundle
   hash, every file against the manifest, the new exe answers `version`; refused while a post is
   between Submit and its result);
2. adds the install folder to the user's PATH, so `punpun-agent` works in a new terminal;
3. makes "punpun Agent" shortcuts (Start menu and desktop) that start `connect` in a window that
   stays open, so errors stay readable;
4. opens the settings window (`agent/settings_gui.py`): a pairing code from the web instead of a
   username and token, the clips folder (Q-33), the customer's videos folder (Q-17) and whether
   the Agent starts with Windows. A "ตั้งค่า punpun Agent" shortcut opens it again later.

`--uninstall` removes the PATH entry, the shortcuts and the program folder. The Agent's data
(installation_id, token, journal) and the clips folder are kept.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agent import updater
from agent.identity import default_data_dir

SHORTCUT = "punpun Agent.lnk"
SETTINGS_SHORTCUT = "ตั้งค่า punpun Agent.lnk"
DESCRIPTIONS = {"connect": "punpun Agent: เชื่อมต่อ server และทำงานที่ตั้งไว้",
                "settings": "punpun Agent: บัญชี โฟลเดอร์คลิป โฟลเดอร์วิดีโอ และการเริ่มเองตอนเปิดเครื่อง"}
START_MENU_GROUP = "punpun"


# --- PATH (HKCU\Environment) ----------------------------------------------------------------------

def _norm(entry: str) -> str:
    # Windows rules (case-insensitive, either slash) on every OS, so the unit tests mean the same on CI
    return ntpath.normcase(os.path.expandvars(entry.strip().strip('"'))).rstrip("\\/")


def path_with(current: str, folder: Path) -> str | None:
    """The user PATH with `folder` appended, or None when it is already there."""
    entries = [e for e in current.split(";") if e.strip()]
    if any(_norm(e) == _norm(str(folder)) for e in entries):
        return None
    return ";".join([*entries, str(folder)])


def path_without(current: str, folder: Path) -> str | None:
    """The user PATH without `folder`, or None when it was not there."""
    entries = [e for e in current.split(";") if e.strip()]
    kept = [e for e in entries if _norm(e) != _norm(str(folder))]
    return None if len(kept) == len(entries) else ";".join(kept)


def _edit_user_path(change) -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        new = change(current)
        if new is None:
            return False
        winreg.SetValueEx(key, "Path", 0, kind, new)
    # Tell Explorer the environment changed, so terminals opened from now on see the new PATH
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
    return True


def add_to_user_path(folder: Path) -> bool:
    return _edit_user_path(lambda current: path_with(current, folder))


def remove_from_user_path(folder: Path) -> bool:
    return _edit_user_path(lambda current: path_without(current, folder))


# --- shortcuts ------------------------------------------------------------------------------------

def _powershell(script: str, env: dict[str, str]) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, **env}, timeout=60)
    if out.returncode != 0:
        raise OSError(out.stderr.strip()[:300] or "powershell failed")
    return out.stdout.strip()


def shortcut_dirs() -> list[Path]:
    """Start menu (Programs\\punpun) and the desktop, as Windows reports them (OneDrive-aware)."""
    out = _powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                      "[Environment]::GetFolderPath('Programs');[Environment]::GetFolderPath('Desktop')", {})
    programs, desktop = out.splitlines()[:2]
    return [Path(programs) / START_MENU_GROUP, Path(desktop)]


def make_shortcut(lnk: Path, launcher: Path, workdir: Path, *, command: str = "connect", minimized: bool = False,
                  keep_open: bool = True, icon: Path | None = None) -> None:
    """A shortcut to `connect` (or another command) in a console that stays open after the Agent stops,
    so errors stay readable. Values travel in environment variables, so no path is ever quoted into
    the script."""
    lnk.parent.mkdir(parents=True, exist_ok=True)
    comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    _powershell("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:PP_LNK);"
                "$s.TargetPath=$env:PP_TARGET;$s.Arguments=$env:PP_ARGS;$s.WorkingDirectory=$env:PP_WD;"
                "$s.Description=$env:PP_DESC;$s.IconLocation=$env:PP_ICON;$s.WindowStyle=[int]$env:PP_STYLE;$s.Save()",
                {"PP_LNK": str(lnk), "PP_TARGET": comspec,
                 "PP_ARGS": f'{"/k" if keep_open else "/c"} ""{launcher}" {command}"',
                 "PP_WD": str(workdir), "PP_DESC": DESCRIPTIONS.get(command, "punpun Agent"),
                 "PP_ICON": f"{icon},0" if icon and icon.is_file() else f"{comspec},0", "PP_STYLE": "7" if minimized else "1"})


# --- setup / uninstall ----------------------------------------------------------------------------

def payload() -> tuple[Path, str, str]:
    """(bundle zip, its SHA-256, default server) carried inside the setup exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "payload"
    info = json.loads((base / "payload.json").read_text(encoding="utf-8"))
    return base / info["bundle"], info["sha256"], info["server"]


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def setup(args) -> int:
    bundle, digest, server = payload()
    root = args.install_dir or updater.default_install_dir()
    data = args.data_dir or default_data_dir()
    print("กำลังติดตั้ง punpun Agent ...")
    try:
        version = updater.install(bundle, root, data_dir=data, expected_sha256=digest)
    except updater.UpdateRefused as exc:
        print(f"ติดตั้งไม่สำเร็จ: {exc}")
        return 1
    launcher = root / "punpun-agent.cmd"
    icon = root / "punpun.ico"  # a stable path for the shortcuts' icon (the exe moves with each version)
    bundled_icon = root / "versions" / version / "_internal" / "agent" / "assets" / "punpun.ico"
    if bundled_icon.is_file():
        shutil.copy2(bundled_icon, icon)
    print(f"ติดตั้งเวอร์ชัน {version} ที่ {root}")
    report = {"installed": version, "launcher": str(launcher), "path_added": False, "shortcuts": []}
    if not args.no_path:
        report["path_added"] = add_to_user_path(root)
        print("เพิ่มคำสั่ง punpun-agent ใน PATH แล้ว (ใช้ได้ในหน้าต่าง terminal ที่เปิดใหม่)"
              if report["path_added"] else "คำสั่ง punpun-agent อยู่ใน PATH อยู่แล้ว")
    if not args.no_shortcuts:
        # Fallback videos folder for `connect` when none is chosen in the settings window (Q-17)
        workdir = Path.home() / "Videos"
        for folder in ([args.shortcut_dir] if args.shortcut_dir else shortcut_dirs()):
            make_shortcut(folder / SHORTCUT, launcher, workdir if workdir.is_dir() else Path.home(), icon=icon)
            make_shortcut(folder / SETTINGS_SHORTCUT, launcher, Path.home(), command="settings", minimized=True,
                          keep_open=False, icon=icon)
            report["shortcuts"] += [str(folder / SHORTCUT), str(folder / SETTINGS_SHORTCUT)]
        print("สร้าง shortcut \"punpun Agent\" และ \"ตั้งค่า punpun Agent\" ที่ Start menu และหน้าจอ desktop แล้ว")
    notices = root / "versions" / version / "adb"
    if notices.is_dir():  # Apache-2.0 §4: say where the licence and notices of the bundled adb are
        print(f"ซอฟต์แวร์ของบุคคลที่สาม (adb จาก Android): สัญญาอนุญาตและประกาศอยู่ที่ {notices}")
    if not args.no_login:
        # The settings window: pairing code, clips folder, videos folder, start with Windows
        print("เปิดหน้าต่างตั้งค่า: ใส่รหัสเชื่อมต่อจากหน้า Agent บนเว็บ แล้วเลือกโฟลเดอร์")
        settings = [str(launcher), "settings", "--server", server]
        if args.data_dir:
            settings += ["--data-dir", str(data)]
        report["settings"] = subprocess.run(settings).returncode
    print(json.dumps(report, ensure_ascii=False))
    return 0


def uninstall(args) -> int:
    root = args.install_dir or updater.default_install_dir()
    busy = updater.posts_in_flight(args.data_dir or default_data_dir())
    if busy:
        print("ยังถอนการติดตั้งไม่ได้: มีโพสต์ที่กดส่งแล้วและรอผลอยู่")
        return 1
    if not args.no_path:
        remove_from_user_path(root)
    for folder in ([args.shortcut_dir] if args.shortcut_dir else shortcut_dirs()):
        (folder / SHORTCUT).unlink(missing_ok=True)
        (folder / SETTINGS_SHORTCUT).unlink(missing_ok=True)
        if folder.name == START_MENU_GROUP and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if not args.shortcut_dir:  # start with Windows (settings window)
        from agent.settings import STARTUP_LINK, startup_folder

        (startup_folder() / STARTUP_LINK).unlink(missing_ok=True)
    shutil.rmtree(root, ignore_errors=True)
    print(f"ถอนการติดตั้งแล้ว (ข้อมูล Agent และโฟลเดอร์คลิปยังอยู่: {args.data_dir or default_data_dir()})")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="punpun-agent-setup")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--install-dir", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--shortcut-dir", type=Path, default=None, help="put the shortcut here only (tests)")
    parser.add_argument("--no-path", action="store_true")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-login", action="store_true")
    parser.add_argument("--no-pause", action="store_true", help="do not wait for Enter at the end")
    args = parser.parse_args(argv)
    try:
        code = uninstall(args) if args.uninstall else setup(args)
    except OSError as exc:
        print(f"เกิดข้อผิดพลาด: {exc}")
        code = 1
    if not args.no_pause and sys.stdin and sys.stdin.isatty():
        _ask("\nกด Enter เพื่อปิดหน้าต่างนี้")  # a double-clicked console closes on exit
    return code


if __name__ == "__main__":
    sys.exit(main())
