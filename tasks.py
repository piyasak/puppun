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
    # Needs the compose Postgres (docker compose up -d postgres); creates and drops its own database.
    "test-integration": [PY, "-m", "pytest", "-q", "services/api/tests", "--rootdir", ".", "-p", "no:cacheprovider"],
}

# Local compose database only (docker-compose.yml). Other environments must set DATABASE_URL.
LOCAL_DATABASE_URL = "postgresql+psycopg://clipflow:clipflow_dev@127.0.0.1:5432/clipflow"

NOT_YET = {
    "dev": "P2 (docker-compose)",
    "seed-demo": "P2",
    "lint": "P1/P2 (ruff + eslint)",
    "typecheck": "P1/P2 (mypy + tsc)",
    "build": "P2",
    "smoke": "P2",
}


def setup() -> int:
    """Create .venv and install the worker package (editable) plus test tools."""
    if not VENV_PY.exists():
        code = subprocess.call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        if code:
            return code
    return subprocess.call([str(VENV_PY), "-m", "pip", "install", "-q", "-e", "services/worker",
                            "-e", "services/api[test]", "pytest"])


def migrate(rest: list[str]) -> int:
    """Apply Alembic migrations (default: upgrade head) to DATABASE_URL or the local compose DB."""
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", LOCAL_DATABASE_URL)
    args = rest or ["upgrade", "head"]
    return subprocess.call([PY, "-m", "alembic", "-c", "services/api/alembic.ini", *args], env=env)


E2E_DATABASE = "clipflow_e2e"
NPX = "npx.cmd" if os.name == "nt" else "npx"


def _local_supabase_env() -> dict[str, str]:
    """Values from `supabase status` of the LOCAL stack (supabase/config.toml)."""
    out = subprocess.run([NPX, "supabase", "status", "-o", "env"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("local Supabase is not running: run `npx supabase start` (see docs/runbooks/supabase-auth.md)")
    values = {}
    for line in out.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


def test_e2e(rest: list[str]) -> int:
    """Playwright journeys on local Supabase + Mailpit, the API on a fresh e2e database, and Vite."""
    sb = _local_supabase_env()
    # Fresh database each run; SQLAlchemy lives in .venv, so this runs there.
    recreate = (
        "import sys; from sqlalchemy import create_engine, text\n"
        "e = create_engine(sys.argv[1], isolation_level='AUTOCOMMIT')\n"
        "with e.connect() as c:\n"
        "    c.execute(text(f'drop database if exists \"{sys.argv[2]}\" with (force)'))\n"
        "    c.execute(text(f'create database \"{sys.argv[2]}\"'))\n"
    )
    code = subprocess.call([PY, "-c", recreate, LOCAL_DATABASE_URL, E2E_DATABASE])
    if code:
        return code
    db_url = LOCAL_DATABASE_URL.rsplit("/", 1)[0] + "/" + E2E_DATABASE
    code = subprocess.call([PY, "-m", "alembic", "-c", "services/api/alembic.ini", "upgrade", "head"],
                           env=os.environ | {"DATABASE_URL": db_url})
    if code:
        return code
    env = os.environ | {
        "E2E_PYTHON": PY,
        "E2E_DATABASE_URL": db_url,
        "E2E_SUPABASE_URL": sb["API_URL"],
        "E2E_SUPABASE_PUBLISHABLE_KEY": sb.get("PUBLISHABLE_KEY") or sb["ANON_KEY"],
        "E2E_MAILPIT_URL": sb.get("MAILPIT_URL") or sb["INBUCKET_URL"],
    }
    return subprocess.call([NPX, "playwright", "test", *rest], cwd=ROOT / "apps" / "web", env=env)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        print("targets:", ", ".join(["setup", "migrate", "test-e2e", "check-gate <phase>", *TARGETS, *NOT_YET]))
        return 2
    target, rest = argv[0], argv[1:]
    if target == "setup":
        return setup()
    if target == "migrate":
        return migrate(rest)
    if target == "test-e2e":
        return test_e2e(rest)
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
