"""Client side of the NF-04 CRUD load test (test_crud_load.py), run as its own process.

    python load_client.py <plan.json> <out.json>

The plan holds the API URL, the run length and one entry per user (bearer token, ids). Each user is a
thread that loops over a mix of everyday web calls with a short think time and records
(endpoint, status, milliseconds). It runs outside the server's process so the two do not share a GIL.
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

URL = "https://www.youtube.com/watch?v=load"


def user_loop(base: str, user: dict, until: float, out: list, lock: threading.Lock) -> None:
    rnd = random.Random(user["token"][-8:])
    headers = {"Authorization": f"Bearer {user['token']}"}
    env, job = user["environment_id"], user["job_id"]
    calls = [
        (5, "GET /v1/me", lambda c: c.get("/v1/me")),
        (3, "GET /v1/workspace/usage", lambda c: c.get("/v1/workspace/usage")),
        (3, "GET /v1/environments", lambda c: c.get("/v1/environments")),
        (6, "GET /v1/jobs", lambda c: c.get("/v1/jobs")),
        (6, "GET /v1/jobs/{id}", lambda c: c.get(f"/v1/jobs/{job}")),
        (3, "GET /v1/devices", lambda c: c.get("/v1/devices")),
        (3, "GET /v1/billing/subscription", lambda c: c.get("/v1/billing/subscription")),
        (3, "GET /v1/schedule-items?attention", lambda c: c.get("/v1/schedule-items", params={"attention": "true"})),
        (2, "PATCH /v1/environments/{id}", lambda c: c.patch(f"/v1/environments/{env}",
                                                            json={"name": f"office-{rnd.randrange(10**6)}"})),
    ]
    weights = [w for w, _, _ in calls]
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        while time.monotonic() < until:
            if rnd.random() < 0.08:  # create a job and cancel it (quota reserve + release)
                t = time.perf_counter()
                r = client.post("/v1/jobs", json={"idempotency_key": uuid.uuid4().hex, "environment_id": env,
                                                  "requested_clips": 1, "source": {"kind": "url", "url": URL}})
                rec = [("POST /v1/jobs", r.status_code, (time.perf_counter() - t) * 1000)]
                if r.status_code == 201:
                    t = time.perf_counter()
                    c = client.post(f"/v1/jobs/{r.json()['id']}/cancel")
                    rec.append(("POST /v1/jobs/{id}/cancel", c.status_code, (time.perf_counter() - t) * 1000))
            else:
                _, name, call = rnd.choices(calls, weights)[0]
                t = time.perf_counter()
                r = call(client)
                rec = [(name, r.status_code, (time.perf_counter() - t) * 1000)]
            with lock:
                out.extend(rec)
            time.sleep(rnd.uniform(0.2, 1.0))


def main(plan_path: str, out_path: str) -> None:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    until = time.monotonic() + plan["seconds"]
    out: list = []
    lock = threading.Lock()
    threads = [threading.Thread(target=user_loop, args=(plan["base"], u, until, out, lock)) for u in plan["users"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
