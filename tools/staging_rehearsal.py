"""Rehearse a staging release on this PC (G2-05, E-49): deploy v1 → release v2 → roll back to v1.

    .venv/Scripts/python tools/staging_rehearsal.py

Uses the real staging image (Dockerfile) against a throwaway database in the local compose Postgres,
with DB_SCHEMA like staging. Each step checks /healthz (which build answers), the web app on the same
origin, an API route, and that no table is in `public`. A rollback is a redeploy of the previous image;
it works because migrations are expand-only between releases (runbook). Summary:
var/evidence/staging_rehearsal.json. This is a rehearsal of the mechanism, not the hosted staging.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "postgresql+psycopg://clipflow:clipflow_dev@127.0.0.1:5432/clipflow"
PORT, SCHEMA = 18080, "clipflow"
PUBLIC_ARGS = ["--build-arg", "VITE_SUPABASE_URL=http://127.0.0.1:54321",
               "--build-arg", "VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_local-rehearsal"]


def sh(*args: str, check: bool = True) -> str:
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and out.returncode:
        raise SystemExit(f"{' '.join(args[:3])}… failed:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
    return out.stdout


def get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def run(tag: str, db_url: str) -> float:
    sh("docker", "rm", "-f", "punpun-staging-rehearsal", check=False)
    started = time.monotonic()
    sh("docker", "run", "-d", "--name", "punpun-staging-rehearsal", "-p", f"{PORT}:8000",
       "--add-host", "host.docker.internal:host-gateway",
       "-e", f"DATABASE_URL={db_url}", "-e", f"DB_SCHEMA={SCHEMA}",
       "-e", "SUPABASE_URL=http://host.docker.internal:54321", "-e", f"WEB_ORIGIN=http://127.0.0.1:{PORT}",
       f"punpun-staging:{tag}")
    for _ in range(120):
        try:
            status, body = get("/healthz")
            if status == 200:
                return time.monotonic() - started
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{tag} never became healthy:\n" + sh("docker", "logs", "punpun-staging-rehearsal", check=False))


def check(tag: str, engine) -> dict:
    status, body = get("/healthz")
    build = json.loads(body)["build"]
    page_status, page = get("/jobs/some-client-route")
    api_status, _ = get("/v1/billing/plans")
    missing_status, missing = get("/v1/does-not-exist")
    insp = inspect(engine)
    result = {
        "build": build, "health": status, "web_route": page_status, "web_is_app": '<div id="root">' in page,
        "api": api_status, "api_404_is_json": missing_status == 404 and '"code"' in missing,
        "tables_in_schema": len(insp.get_table_names(schema=SCHEMA)), "tables_in_public": len(insp.get_table_names(schema="public")),
    }
    with engine.connect() as c:
        result["alembic"] = c.execute(text(f'select version_num from "{SCHEMA}".alembic_version')).scalar()
    ok = (build == tag and status == page_status == api_status == 200 and result["web_is_app"]
          and result["api_404_is_json"] and result["tables_in_public"] == 0 and result["tables_in_schema"] > 10)
    if not ok:
        raise SystemExit(f"{tag} check failed: {result}")
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    name = f"clipflow_staging_rehearsal_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'create database "{name}"'))
    db_url = f"postgresql+psycopg://clipflow:clipflow_dev@host.docker.internal:5432/{name}"
    engine = create_engine(ADMIN.rsplit("/", 1)[0] + f"/{name}")
    steps = []
    try:
        for tag in ("v1", "v2"):
            sh("docker", "build", "-q", "-t", f"punpun-staging:{tag}", "--build-arg", f"BUILD_ID={tag}", *PUBLIC_ARGS, str(ROOT))
        for step, tag in (("deploy", "v1"), ("release", "v2"), ("rollback", "v1")):
            seconds = run(tag, db_url)
            steps.append({"step": step, "tag": tag, "healthy_after_s": round(seconds, 1), **check(tag, engine)})
            print(f"{step:8s} {tag}: healthy in {seconds:.1f}s, {steps[-1]}")
    finally:
        sh("docker", "rm", "-f", "punpun-staging-rehearsal", check=False)
        engine.dispose()
        with admin.connect() as c:
            c.execute(text(f'drop database if exists "{name}" with (force)'))
        admin.dispose()
    out = ROOT / "var" / "evidence" / "staging_rehearsal.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "steps": steps}, indent=2), encoding="utf-8")
    print(f"ok → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
