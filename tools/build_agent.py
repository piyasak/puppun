"""Build the Windows Agent bundle (P5.6, E-44).

    .venv/Scripts/python tools/build_agent.py

PyInstaller (onedir) packs the Agent and the media worker with Python itself, so the customer's PC
needs no Python. The result is zipped with a manifest of every file's SHA-256 and the version:
var/dist/punpun-agent-<version>.zip and .zip.sha256 (var/ is never committed). `agent.cli install`
accepts only a bundle whose files all match this manifest.

It also builds the double-click setup (E-50): var/dist/punpun-agent-setup-<version>.exe (+ .sha256),
one PyInstaller onefile exe that carries the bundle, its SHA-256 and the default server
(CLIPFLOW_SETUP_SERVER, default the staging URL) and runs agent/setup_win.py.

FFmpeg and adb are not bundled: they are separate downloads the setup guide points to, and
`agent.cli status`/`doctor` report when they are missing.
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
           "--collect-submodules", "yt_dlp", str(ROOT / "agent" / "__main__.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    app = WORK / "dist" / "punpun-agent"
    (app / "version.txt").write_text(version, encoding="ascii")  # what the packaged exe reports
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
           str(ROOT / "agent" / "setup_win.py")]
    subprocess.run(cmd, check=True, cwd=ROOT)
    setup = OUT / f"{name}.exe"
    (OUT / f"{setup.name}.sha256").write_text(f"{sha256(setup)}  {setup.name}\n", encoding="ascii")
    return setup


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
