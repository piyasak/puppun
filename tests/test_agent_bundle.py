"""Opt-in (G5-01): the real packaged Agent on this Windows PC — install, self-update, roll back.

    .venv/Scripts/python tools/build_agent.py 0.2.0 && .venv/Scripts/python tools/build_agent.py 0.3.0
    CLIPFLOW_AGENT_BUNDLE=1 CLIPFLOW_BUNDLE_TO=0.3.0 .venv/Scripts/python -m pytest tests/test_agent_bundle.py -s

FROM/TO default to 0.2.0/0.2.1 (G5-01); 0.3.0 adds the clips folder (Q-33), checked when TO has it.

The packaged exe (Nuitka-compiled from 0.4.0, no Python needed on the PC) installs the next version itself and
rolls back through the launcher. A summary goes to var/evidence/p56_agent_bundle.json.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "var" / "dist"
FROM = os.environ.get("CLIPFLOW_BUNDLE_FROM", "0.2.0")
TO = os.environ.get("CLIPFLOW_BUNDLE_TO", "0.2.1")
pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_AGENT_BUNDLE") != "1",
                                reason="needs built bundles (tools/build_agent.py); opt-in CLIPFLOW_AGENT_BUNDLE=1")


def sha(version: str) -> str:
    return (DIST / f"punpun-agent-{version}.zip.sha256").read_text(encoding="ascii").split()[0]


def test_packaged_agent_install_update_rollback(tmp_path):
    root, data = tmp_path / "app", tmp_path / "data"
    launcher = root / "punpun-agent.cmd"

    def agent(*args):
        out = subprocess.run([str(launcher), *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300)  # the CLI writes UTF-8 (Thai messages)
        return out.returncode, out.stdout.strip()

    first = subprocess.run([os.sys.executable, "-m", "agent", "install", "--bundle", str(DIST / f"punpun-agent-{FROM}.zip"),
                            "--sha256", sha(FROM), "--install-dir", str(root), "--data-dir", str(data)],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert first.returncode == 0, first.stdout + first.stderr
    assert agent("version") == (0, FROM)
    code, out = agent("install", "--bundle", str(DIST / f"punpun-agent-{TO}.zip"), "--sha256", sha(TO),
                      "--install-dir", str(root), "--data-dir", str(data))
    assert code == 0, out
    assert agent("version") == (0, TO)  # the running FROM exe installed TO
    assert agent("install", "--bundle", str(DIST / f"punpun-agent-{TO}.zip"), "--sha256", "0" * 64,
                 "--install-dir", str(root), "--data-dir", str(data))[0] == 1
    steps = [f"install {FROM}", f"self-update to {TO}", "bad sha refused"]
    folder = {}
    if TO >= "0.3.0":  # Q-33: the clips folder, on the packaged exe
        data.mkdir(parents=True, exist_ok=True)
        (data / "config.json").write_text(json.dumps({"server": "https://example.invalid", "username": "qa"}),
                                          encoding="utf-8")  # as left by a pre-0.3.0 login
        old = data / "clips" / "job-1"
        old.mkdir(parents=True)
        (old / "clip_01.mp4").write_bytes(b"kept")
        code, out = agent("set-folder", "relative\path", "--data-dir", str(data))
        assert code == 2 and "path" in out  # must be a full path
        target = tmp_path / "Videos" / "punpun"
        code, out = agent("set-folder", str(target), "--move", "--data-dir", str(data))
        assert code == 0, out
        folder = json.loads(out)
        assert folder["clips_folder"] == str(target.resolve()) and folder["moved_jobs"] == 1
        assert (target / "job-1" / "clip_01.mp4").read_bytes() == b"kept" and not old.exists()
        code, out = agent("status", "--data-dir", str(data))
        assert json.loads(out)["clips_folder"] == str(target.resolve())
        steps += ["set-folder refuses a relative path", "set-folder --move moves the clips already made",
                  "status shows the folder"]
    assert agent("rollback", "--install-dir", str(root), "--data-dir", str(data))[0] == 0
    assert agent("version") == (0, FROM)
    code, out = agent("status", "--data-dir", str(data))
    assert code == 0, out  # the older Agent still reads a config that has clips_dir
    status = json.loads(out)
    steps.append(f"rollback to {FROM} (still reads the config)")
    (ROOT / "var" / "evidence").mkdir(parents=True, exist_ok=True)
    (ROOT / "var" / "evidence" / f"agent_bundle_{FROM}_to_{TO}.json").write_text(json.dumps({
        "windows": platform.platform(), "bundles": {v: sha(v) for v in (FROM, TO)},
        "steps": steps, "set_folder": folder, "status_phones": status["phones"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    assert status["version"] == FROM
