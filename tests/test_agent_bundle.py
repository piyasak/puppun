"""Opt-in (G5-01): the real packaged Agent on this Windows PC — install, self-update, roll back.

    .venv/Scripts/python tools/build_agent.py 0.2.0 && .venv/Scripts/python tools/build_agent.py 0.2.1
    CLIPFLOW_AGENT_BUNDLE=1 .venv/Scripts/python -m pytest tests/test_agent_bundle.py -s

The packaged exe (PyInstaller, no Python needed on the PC) installs the next version itself and
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
pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_AGENT_BUNDLE") != "1",
                                reason="needs built bundles (tools/build_agent.py); opt-in CLIPFLOW_AGENT_BUNDLE=1")


def sha(version: str) -> str:
    return (DIST / f"punpun-agent-{version}.zip.sha256").read_text(encoding="ascii").split()[0]


def test_packaged_agent_install_update_rollback(tmp_path):
    root, data = tmp_path / "app", tmp_path / "data"
    launcher = root / "punpun-agent.cmd"

    def agent(*args):
        out = subprocess.run([str(launcher), *args], capture_output=True, text=True, timeout=300)
        return out.returncode, out.stdout.strip()

    first = subprocess.run([os.sys.executable, "-m", "agent", "install", "--bundle", str(DIST / "punpun-agent-0.2.0.zip"),
                            "--sha256", sha("0.2.0"), "--install-dir", str(root), "--data-dir", str(data)],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert first.returncode == 0, first.stdout + first.stderr
    assert agent("version") == (0, "0.2.0")
    code, out = agent("install", "--bundle", str(DIST / "punpun-agent-0.2.1.zip"), "--sha256", sha("0.2.1"),
                      "--install-dir", str(root), "--data-dir", str(data))
    assert code == 0, out
    assert agent("version") == (0, "0.2.1")  # the running 0.2.0 exe installed 0.2.1
    assert agent("install", "--bundle", str(DIST / "punpun-agent-0.2.1.zip"), "--sha256", "0" * 64,
                 "--install-dir", str(root), "--data-dir", str(data))[0] == 1
    assert agent("rollback", "--install-dir", str(root), "--data-dir", str(data))[0] == 0
    assert agent("version") == (0, "0.2.0")
    code, out = agent("status", "--data-dir", str(data))
    status = json.loads(out)
    (ROOT / "var" / "evidence").mkdir(parents=True, exist_ok=True)
    (ROOT / "var" / "evidence" / "p56_agent_bundle.json").write_text(json.dumps({
        "windows": platform.platform(), "bundles": {v: sha(v) for v in ("0.2.0", "0.2.1")},
        "steps": ["install 0.2.0", "self-update to 0.2.1", "bad sha refused", "rollback to 0.2.0"],
        "status_phones": status["phones"],
    }, indent=2), encoding="utf-8")
    assert status["version"] == "0.2.0"
