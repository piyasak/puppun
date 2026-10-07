"""Windows-friendly task runner mirroring the Makefile targets (PRD section I).

Usage: py tasks.py <target> [args]. Targets that belong to a later phase exit
non-zero with a message instead of pretending to succeed.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
# Use the project venv once `setup` has created it; check-gate itself needs only the stdlib.
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

TARGETS = {
    "test-unit": [PY, "-m", "pytest", "-q", "tests/unit", "services/worker/tests",
                  "--rootdir", ".", "-p", "no:cacheprovider"],
}

NOT_YET = {
    "dev": "P2 (docker-compose)",
    "migrate": "P2 (Alembic)",
    "seed-demo": "P2",
    "lint": "P1/P2 (ruff + eslint)",
    "typecheck": "P1/P2 (mypy + tsc)",
    "test-integration": "P2",
    "test-e2e": "P2/P3",
    "build": "P2",
    "smoke": "P2",
}


def setup() -> int:
    """Create .venv and install the worker package (editable) plus test tools."""
    if not VENV_PY.exists():
        code = subprocess.call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        if code:
            return code
    return subprocess.call([str(VENV_PY), "-m", "pip", "install", "-q", "-e", "services/worker", "pytest"])


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        print("targets:", ", ".join(["check-gate <phase>", *TARGETS, *NOT_YET]))
        return 2
    target, rest = argv[0], argv[1:]
    if target == "setup":
        return setup()
    if target == "check-gate":
        return subprocess.call([PY, "-m", "tools.check_gate", *rest])
    if target in TARGETS:
        return subprocess.call(TARGETS[target] + rest)
    if target in NOT_YET:
        print(f"'{target}' is not implemented yet; planned for {NOT_YET[target]}.")
        return 3
    print(f"unknown target: {target}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
