"""Build the Windows Agent bundle (P5.6, E-44).

    .venv/Scripts/python tools/build_agent.py

PyInstaller (onedir) packs the Agent and the media worker with Python itself, so the customer's PC
needs no Python. The result is zipped with a manifest of every file's SHA-256 and the version:
var/dist/punpun-agent-<version>.zip and .zip.sha256 (var/ is never committed). `agent.cli install`
accepts only a bundle whose files all match this manifest.

It also builds the double-click setup (E-50): var/dist/punpun-agent-setup-<version>.exe (+ .sha256),
one PyInstaller onefile exe that carries the bundle, its SHA-256 and the default server
(CLIPFLOW_SETUP_SERVER, default the staging URL) and runs agent/setup_win.py.

adb comes with the Agent (E-51: adb.exe + its two DLLs, NOTICE.txt and source.properties from
Android platform-tools, in an adb folder next to the exe). FFmpeg is not bundled: it is a separate download, and
`agent.cli status`/`doctor` report when it is missing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "dist"
WORK = ROOT / "var" / "build-agent"
ICON = ROOT / "agent" / "assets" / "punpun.ico"  # from logo/sub.png
SERVER = os.environ.get("CLIPFLOW_SETUP_SERVER", "https://punpun-staging.onrender.com")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main(version_override: str | None = None) -> int:
    sys.path.insert(0, str(ROOT))
    from agent import SOURCE_VERSION

    version = version_override or SOURCE_VERSION
    shutil.rmtree(WORK, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
           "--name", "punpun-agent", "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "build"),
           "--specpath", str(WORK), "--paths", str(ROOT), "--paths", str(ROOT / "services" / "worker"),
           "--collect-submodules", "agent", "--collect-submodules", "clipflow_worker",
           "--collect-submodules", "yt_dlp", "--icon", str(ICON),
           "--add-data", f"{ROOT / 'agent' / 'assets'}{os.pathsep}agent/assets",  # logo for the settings window
           str(ROOT / "agent" / "__main__.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    app = WORK / "dist" / "punpun-agent"
    (app / "version.txt").write_text(version, encoding="ascii")  # what the packaged exe reports
    copy_adb(app / "adb")
    copy_scrcpy(app / "scrcpy")
    files = {p.relative_to(app).as_posix(): sha256(p) for p in sorted(app.rglob("*")) if p.is_file()}
    manifest = {"version": version, "files": files}
    OUT.mkdir(parents=True, exist_ok=True)
    bundle = OUT / f"punpun-agent-{version}.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(app / name, name)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    digest = sha256(bundle)
    (OUT / f"{bundle.name}.sha256").write_text(f"{digest}  {bundle.name}\n", encoding="ascii")
    setup = build_setup(version, bundle, digest)
    print(json.dumps({"bundle": str(bundle), "sha256": digest, "files": len(files),
                      "size_mb": round(bundle.stat().st_size / 1e6, 1),
                      "setup": str(setup), "setup_sha256": sha256(setup),
                      "setup_size_mb": round(setup.stat().st_size / 1e6, 1), "server": SERVER}, indent=2))
    return 0


ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt", "source.properties")


def copy_adb(target: Path) -> None:
    """The Agent's own adb (E-51) from Android platform-tools (CLIPFLOW_PLATFORM_TOOLS, else the adb on
    PATH), so a customer PC needs no Android SDK. Its licence notice and version travel with it."""
    folder = os.environ.get("CLIPFLOW_PLATFORM_TOOLS")
    source = Path(folder) if folder else Path(shutil.which("adb") or "").parent
    missing = [n for n in ADB_FILES if not (source / n).is_file()]
    if missing:
        raise SystemExit(f"platform-tools not found or incomplete at {source} (missing {missing}); "
                         "set CLIPFLOW_PLATFORM_TOOLS")
    target.mkdir(parents=True, exist_ok=True)
    for name in ADB_FILES:
        shutil.copy2(source / name, target / name)
        if sha256(target / name) != sha256(source / name):
            raise SystemExit(f"{name} changed while copying")
    # Apache-2.0 §4: the licence text, the original NOTICE (copied above, unchanged) and a statement
    # that the binaries are unmodified, next to them (E-51).
    shutil.copy2(ROOT / "agent" / "licenses" / "Apache-2.0.txt", target / "LICENSE.txt")
    revision = next((line.split("=", 1)[1].strip() for line in (source / "source.properties").read_text(
        encoding="utf-8").splitlines() if line.startswith("Pkg.Revision")), "unknown")
    lines = ["adb for punpun Agent", "",
             f"adb.exe, AdbWinApi.dll and AdbWinUsbApi.dll are Android SDK Platform-Tools {revision},",
             "Copyright The Android Open Source Project (Google LLC). They are included UNMODIFIED:",
             "punpun has not changed their source code or the files themselves.", "",
             "Licence: LICENSE.txt (Apache License 2.0). Notices of the original package: NOTICE.txt (unchanged).",
             "Source code: https://android.googlesource.com/platform/packages/modules/adb", "",
             "SHA-256 (identical to the files in the original Platform-Tools package):"]
    lines += [f"  {sha256(target / n)}  {n}" for n in ADB_FILES if n.endswith((".exe", ".dll"))]
    (target / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    probe = subprocess.run([str(target / "adb.exe"), "version"], capture_output=True, text=True, timeout=60)
    if probe.returncode != 0 or "Android Debug Bridge" not in probe.stdout:
        raise SystemExit(f"the copied adb does not start on its own: {probe.stdout or probe.stderr}")


SCRCPY_DIR = ROOT / "var" / "vendor" / "scrcpy-4.1" / "scrcpy-win64-v4.1"  # from the published zip, SHA-256 checked
SCRCPY_SKIP = {"adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "open_a_terminal_here.bat", "scrcpy-noconsole.vbs"}


def copy_scrcpy(target: Path) -> None:
    """Phone screens on the PC (PO 2026-10-10): scrcpy (Genymobile, Apache-2.0), unmodified. Its own adb is
    left out: the Agent passes its bundled adb (ADB=...), so one adb version serves both (E-51)."""
    source = Path(os.environ.get("CLIPFLOW_SCRCPY_DIR") or SCRCPY_DIR)
    if not (source / "scrcpy.exe").is_file():
        print(f"scrcpy not found at {source}: the bundle has no phone screens (set CLIPFLOW_SCRCPY_DIR)")
        return
    target.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in source.iterdir() if p.is_file() and p.name not in SCRCPY_SKIP)
    for name in names:
        shutil.copy2(source / name, target / name)
    version = subprocess.run([str(target / "scrcpy.exe"), "--version"], capture_output=True, text=True,
                             timeout=60).stdout.splitlines()[0]
    lines = ["scrcpy for punpun Agent (phone screens on the PC)", "",
             f"{version} by Genymobile, included UNMODIFIED from the published Windows release.",
             "Licence: LICENSE.txt (Apache License 2.0). Source: https://github.com/Genymobile/scrcpy", "",
             "Libraries shipped by that release, unmodified: FFmpeg (avcodec, avformat, avutil, swresample; LGPL),",
             "SDL3 (zlib licence), libusb (LGPL-2.1). Sources: https://ffmpeg.org, https://libsdl.org,",
             "https://libusb.info. scrcpy's own adb is not included: the Agent's adb (../adb) is used.", "",
             "SHA-256:"]
    lines += [f"  {sha256(target / n)}  {n}" for n in names]
    (target / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_setup(version: str, bundle: Path, digest: str) -> Path:
    """punpun-agent-setup-<version>.exe: agent/setup_win.py with the bundle inside (E-50)."""
    payload = WORK / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, payload / bundle.name)
    (payload / "payload.json").write_text(json.dumps({"bundle": bundle.name, "sha256": digest, "server": SERVER}),
                                          encoding="utf-8")
    name = f"punpun-agent-setup-{version}"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
           "--name", name, "--distpath", str(OUT), "--workpath", str(WORK / "build-setup"),
           "--specpath", str(WORK), "--paths", str(ROOT), "--add-data", f"{payload}{os.pathsep}payload",
           "--icon", str(ICON),
           str(ROOT / "agent" / "setup_win.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    setup = OUT / f"{name}.exe"
    (OUT / f"{setup.name}.sha256").write_text(f"{sha256(setup)}  {setup.name}\n", encoding="ascii")
    return setup


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
