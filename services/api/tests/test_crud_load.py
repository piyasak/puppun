"""Opt-in load test for NF-04 / G7-04: p95 < 1 s for everyday CRUD with 50 concurrent users.

    CLIPFLOW_LOAD=1 .venv/Scripts/python -m pytest services/api/tests/test_crud_load.py -s

50 onboarded Workspaces, each with an Environment, a phone and a job with clips. One API process
(uvicorn, single worker: a conservative setup) serves real HTTP; the 50 users run in a separate
process (`load_client.py`) so client threads do not share the server's GIL. Each user loops over
reads, an Environment rename and an occasional job create + cancel with 0.2–1 s think time for
SECONDS. Render, download and posting are not part of NF-04. A summary is written to
var/evidence/p7_crud_load.json.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CLIPFLOW_LOAD") != "1", reason="load test is opt-in (CLIPFLOW_LOAD=1)")

USERS, SECONDS = 50, 60
EVIDENCE = Path(__file__).resolve().parents[3] / "var" / "evidence" / "p7_crud_load.json"


def p95(values):
    return statistics.quantiles(values, n=100)[94] if len(values) >= 20 else max(values)


def test_crud_p95_under_one_second_with_50_users(onboard, client, real_clip, server_url, tmp_path):
    from api_test_shop import Shop

    users = []
    for _ in range(USERS):
        shop = Shop(onboard(), client, real_clip)
        job_id, _ = shop.job(clips=2)
        users.append({"token": shop.acc.token, "environment_id": shop.env["id"], "job_id": job_id})
    plan, out = tmp_path / "plan.json", tmp_path / "out.json"
    plan.write_text(json.dumps({"base": server_url, "seconds": SECONDS, "users": users}), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).with_name("load_client.py")), str(plan), str(out)],
                   check=True, timeout=SECONDS + 120)

    records = json.loads(out.read_text(encoding="utf-8"))
    by_name = defaultdict(list)
    errors = [r for r in records if r[1] >= 500]
    for name, _, ms in records:
        by_name[name].append(ms)
    every = [ms for _, _, ms in records]
    summary = {
        "users": USERS, "seconds": SECONDS, "requests": len(records),
        "throughput_rps": round(len(records) / SECONDS, 1), "server_errors": len(errors),
        "p50_ms": round(statistics.median(every), 1), "p95_ms": round(p95(every), 1), "max_ms": round(max(every), 1),
        "per_endpoint": {k: {"n": len(v), "p95_ms": round(p95(v), 1)} for k, v in sorted(by_name.items())},
        "statuses": sorted({f"{n} {s}" for n, s, _ in records}),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    assert not errors, errors[:5]
    assert summary["p95_ms"] < 1000
    assert all(e["p95_ms"] < 1000 for e in summary["per_endpoint"].values())
