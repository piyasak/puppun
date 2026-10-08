"""Install, update and roll back the packaged Agent (P5.6, G5-01, E-44).

Layout (per Windows user, no admin rights):

    %LOCALAPPDATA%\\Programs\\punpun-agent\\
        versions\\<version>\\punpun-agent.exe (+ _internal\\, manifest.json)
        current            the version the launcher starts
        previous           the version a rollback returns to
        punpun-agent.cmd   launcher: starts versions\\<current>\\punpun-agent.exe

The Agent's data (installation_id, token, journal, clips) lives in a separate folder and is never
touched by an update, so a new version keeps its registration and history.

An update is refused while a post is between Submit and its result (journal SUBMITTING/VERIFYING):
replacing the Agent then could lose track of a post that may already be live (PRD P5.6). A bundle is
accepted only if its SHA-256 matches, every file matches its manifest hash, nothing extra is in it,
and the new executable answers `version` with the version it claims. Switching versions is a rename
of one small file, so a crash leaves either the old or the new version active, never half of each.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

EXE = "punpun-agent.exe"
MANIFEST = "manifest.json"
KEEP = 3  # installed versions kept (current, previous and one more)
IN_FLIGHT = {"SUBMITTING", "VERIFYING"}


class UpdateRefused(Exception):
    pass


def default_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Programs" / "punpun-agent"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def version_key(version: str) -> tuple:
    """"0.10.0" sorts after "0.2.0"."""
    return tuple(int(p) if p.isdigit() else p for p in version.replace("-", ".").split("."))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip() or None
    except FileNotFoundError:
        return None


def _write(path: Path, value: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(value, encoding="ascii")
    os.replace(tmp, path)


@dataclass
class InstallState:
    current: str | None
    previous: str | None
    installed: list[str]


def state(root: Path) -> InstallState:
    versions = root / "versions"
    installed = sorted((p.name for p in versions.iterdir() if p.is_dir() and not p.name.endswith(".tmp")),
                       key=version_key) if versions.exists() else []
    return InstallState(_read(root / "current"), _read(root / "previous"), installed)


def posts_in_flight(data_dir: Path | None) -> list[str]:
    """Attempts whose last journal state is SUBMITTING or VERIFYING (the Post may be live)."""
    journal = data_dir / "attempts.jsonl" if data_dir else None
    if not journal or not journal.exists():
        return []
    last: dict[str, str] = {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        last[row["attempt_id"]] = row["state"]
    return [a for a, s in last.items() if s in IN_FLIGHT]


def _launcher(root: Path) -> None:
    (root / "punpun-agent.cmd").write_text(
        "@echo off\r\n"
        "set /p V=<\"%~dp0current\"\r\n"
        "\"%~dp0versions\\%V%\\" + EXE + "\" %*\r\n", encoding="ascii")


def install(bundle: Path, root: Path, *, data_dir: Path | None = None, expected_sha256: str | None = None,
            run=subprocess.run) -> str:
    """Install `bundle` and make it current. Returns the installed version."""
    busy = posts_in_flight(data_dir)
    if busy:
        raise UpdateRefused(f"a post is between Submit and its result ({len(busy)}); update after it is settled")
    if expected_sha256 and sha256_file(bundle) != expected_sha256.lower():
        raise UpdateRefused("bundle SHA-256 does not match the published value")
    with zipfile.ZipFile(bundle) as zf:
        try:
            manifest = json.loads(zf.read(MANIFEST))
            version, files = manifest["version"], manifest["files"]
        except (KeyError, ValueError):
            raise UpdateRefused("bundle has no valid manifest") from None
        names = {n for n in zf.namelist() if not n.endswith("/")}
        if names != set(files) | {MANIFEST}:
            raise UpdateRefused("bundle contents do not match its manifest")
        if any(n.startswith(("/", "\\")) or ".." in Path(n).parts or ":" in n for n in names):
            raise UpdateRefused("bundle contains unsafe paths")
        target = root / "versions" / version
        if target.exists() and state(root).current == version:
            return version  # already installed and current
        staging = root / "versions" / f"{version}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        zf.extractall(staging)
    for name, digest in files.items():
        if sha256_file(staging / name) != digest:
            shutil.rmtree(staging, ignore_errors=True)
            raise UpdateRefused(f"file {name} does not match the manifest")
    probe = run([str(staging / EXE), "version"], capture_output=True, text=True, timeout=60)
    if probe.returncode != 0 or probe.stdout.strip() != version:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateRefused(f"new version did not start correctly ({probe.stdout.strip()[:60]!r})")
    shutil.rmtree(target, ignore_errors=True)
    _rename_when_free(staging, target)
    before = state(root).current
    if before and before != version:
        _write(root / "previous", before)
    _write(root / "current", version)  # the switch: one atomic rename
    _launcher(root)
    _prune(root)
    return version


def _rename_when_free(src: Path, dst: Path, tries: int = 20, wait_s: float = 0.5) -> None:
    """Windows keeps a just-run exe locked for a moment (process exit, antivirus scan): retry briefly.
    Seen on the QA PC, 2026-10-08: "Access is denied" right after the smoke test."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt + 1 == tries:
                shutil.rmtree(src, ignore_errors=True)
                raise UpdateRefused("the new version's folder stayed locked; try the update again") from None
            time.sleep(wait_s)


def rollback(root: Path, *, data_dir: Path | None = None) -> str:
    st = state(root)
    if not st.previous or st.previous not in st.installed:
        raise UpdateRefused("no previous version to roll back to")
    busy = posts_in_flight(data_dir)
    if busy:
        raise UpdateRefused("a post is between Submit and its result; roll back after it is settled")
    _write(root / "previous", st.current or "")
    _write(root / "current", st.previous)
    return st.previous


def _prune(root: Path) -> None:
    st = state(root)
    keep = {v for v in (st.current, st.previous) if v}
    others = [v for v in st.installed if v not in keep]
    for old in others[: max(0, len(st.installed) - KEEP)]:
        shutil.rmtree(root / "versions" / old, ignore_errors=True)
