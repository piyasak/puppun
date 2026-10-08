"""P5.1/P5.6 (G5-01): install/update/rollback rules, token storage, compatibility matrix.

Bundles here are synthetic zips with a fake executable (the smoke run is injected). The real
packaged bundles are exercised by tests/test_agent_bundle.py (opt-in, after tools/build_agent.py).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agent import compat, credentials, updater


def bundle(tmp: Path, version: str, *, tamper=False, extra=False) -> Path:
    files = {"punpun-agent.exe": f"exe {version}".encode(), "_internal/lib.dll": b"lib", "version.txt": version.encode()}
    manifest = {"version": version, "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    path = tmp / f"b-{version}{'-t' if tamper else ''}{'-x' if extra else ''}.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data + (b"!" if tamper and name.endswith(".dll") else b""))
        if extra:
            zf.writestr("evil.exe", b"x")
        zf.writestr("manifest.json", json.dumps(manifest))
    return path


def runs_as(version_of_exe):
    def run(cmd, **kw):
        exe = Path(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, stdout=(exe.parent / "version.txt").read_text() + "\n", stderr="")
    return run


def test_install_update_and_rollback(tmp_path):
    root = tmp_path / "app"
    run = runs_as(None)
    assert updater.install(bundle(tmp_path, "0.2.0"), root, run=run) == "0.2.0"
    assert updater.install(bundle(tmp_path, "0.2.1"), root, run=run) == "0.2.1"
    st = updater.state(root)
    assert (st.current, st.previous, st.installed) == ("0.2.1", "0.2.0", ["0.2.0", "0.2.1"])
    assert "versions\\%V%\\punpun-agent.exe" in (root / "punpun-agent.cmd").read_text()
    assert updater.rollback(root) == "0.2.0"
    assert updater.state(root).current == "0.2.0" and updater.state(root).previous == "0.2.1"


def test_bundles_that_do_not_match_are_refused(tmp_path):
    root, run = tmp_path / "app", runs_as(None)
    good = bundle(tmp_path, "0.2.0")
    with pytest.raises(updater.UpdateRefused, match="SHA-256"):
        updater.install(good, root, expected_sha256="0" * 64, run=run)
    with pytest.raises(updater.UpdateRefused, match="manifest"):
        updater.install(bundle(tmp_path, "0.2.0", tamper=True), root, run=run)
    with pytest.raises(updater.UpdateRefused, match="manifest"):
        updater.install(bundle(tmp_path, "0.2.0", extra=True), root, run=run)

    def wrong_version(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="9.9.9\n", stderr="")

    with pytest.raises(updater.UpdateRefused, match="did not start"):
        updater.install(good, root, run=wrong_version)
    assert updater.state(root).current is None and updater.state(root).installed == []


def test_no_update_or_rollback_while_a_post_may_be_live(tmp_path):
    root, data, run = tmp_path / "app", tmp_path / "data", runs_as(None)
    updater.install(bundle(tmp_path, "0.2.0"), root, run=run)
    updater.install(bundle(tmp_path, "0.2.1"), root, run=run)
    data.mkdir()
    journal = data / "attempts.jsonl"
    journal.write_text(json.dumps({"attempt_id": "p-1", "state": "SUBMITTING", "at": 0}) + "\n", encoding="utf-8")
    with pytest.raises(updater.UpdateRefused, match="between Submit"):
        updater.install(bundle(tmp_path, "0.2.2"), root, data_dir=data, run=run)
    with pytest.raises(updater.UpdateRefused, match="between Submit"):
        updater.rollback(root, data_dir=data)
    with open(journal, "a", encoding="utf-8") as fh:  # settled: verified
        fh.write(json.dumps({"attempt_id": "p-1", "state": "VERIFIED_SUCCESS", "at": 1}) + "\n")
    assert updater.install(bundle(tmp_path, "0.2.2"), root, data_dir=data, run=run) == "0.2.2"


def test_old_versions_are_pruned_and_versions_sort_numerically(tmp_path):
    root, run = tmp_path / "app", runs_as(None)
    for v in ("0.2.0", "0.9.0", "0.10.0", "0.11.0"):
        updater.install(bundle(tmp_path, v), root, run=run)
    st = updater.state(root)
    assert st.current == "0.11.0" and st.previous == "0.10.0"
    assert st.installed == ["0.9.0", "0.10.0", "0.11.0"]  # 0.2.0 removed, numeric order


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_token_is_encrypted_for_this_windows_user(tmp_path):
    token = "cfat_ABCDEFGHIJ_" + "x" * 43
    credentials.save_token(tmp_path, token)
    blob = (tmp_path / "token.bin").read_bytes()
    assert token.encode() not in blob and b"cfat_" not in blob
    assert credentials.load_token(tmp_path) == token
    credentials.save_config(tmp_path, credentials.AgentConfig("https://api.example", "shop1"))
    assert credentials.load_config(tmp_path) == credentials.AgentConfig("https://api.example", "shop1")
    credentials.forget_token(tmp_path)
    assert credentials.load_token(tmp_path) is None


def test_only_the_tested_phone_and_tiktok_are_driven():
    assert compat.check_phone("25078PC3EG", "15", "com.ss.android.ugc.trill", "40.0.0").supported
    for args, why in [(("SM-A556E", "15", "com.ss.android.ugc.trill", "40.0.0"), "model"),
                      (("25078PC3EG", "14", "com.ss.android.ugc.trill", "40.0.0"), "Android"),
                      (("25078PC3EG", "15", "com.ss.android.ugc.trill", "41.2.0"), "TikTok")]:
        verdict = compat.check_phone(*args)
        assert not verdict.supported and why in verdict.reason
    assert compat.check_windows("Windows", 26100).supported
    assert not compat.check_windows("Windows", 19045).supported
    assert not compat.check_windows("Linux", 0).supported
