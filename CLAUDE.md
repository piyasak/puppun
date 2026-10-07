# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

Phases 0 and P1 are in progress: G0 and G1 are No. Clips are 3–5 minutes (D02); P1 phone testing happens on a separate QA machine (Q-13), and no SaaS application exists yet. What exists:
- `PRD_CLAUDE_CODE.md`: the product source of truth. Sections A–N are the implementation contract; section O is the full Thai PRD with the 47 gate checks and UAT cases. The `.docx` is the original and duplicates section O.
- `docs/`: progress (read first), architecture, decisions (D/Q/E registers, including PO answers from 2026-10-06), requirements-map, ui-map, backlog, compatibility (real source/device results), and `gates/G0–G8.md`.
- `services/worker/clipflow_worker/`: the P1 media POC.
  - `source.py`: yt-dlp adapter with a URL allowlist, an SSRF guard on media URLs, and error classification.
  - `segments.py`: audio-pause boundaries plus seeded selection.
  - `textlayout.py`: Thai-safe line wrapping.
  - `render.py`: 9:16 output via libass/.ass.
  - `poc.py`: the CLI.
- `agent/`: the P1 Agent POC. It has an ADB adapter, a write-ahead attempt journal (`attempt.py`) and a CLI. It has not been tested on a real phone yet.
- `docker-compose.yml`: local Postgres 16, Redis 7 and MinIO (private bucket `clipflow-media`), bound to 127.0.0.1.
- `tools/check_gate.py`, `tasks.py` (the Windows task runner; there is no `make`) and a `Makefile` wrapper.

Generated media and evidence go under `var/`, which is gitignored and never committed.

## Execution rules (from PRD §C)

- Read `PRD_CLAUDE_CODE.md` and `docs/progress.md` before starting a new task.
- Work in phase order (P0 → P8). A gate marked No blocks dependent production work. Start with P0 (assessment, requirements map, decisions, backlog, gate register), then the P1 feasibility POC. Do not attempt the 12-week plan as one change.
- Keep FR-01–24, NF-01–10 and the gate check IDs traceable in `docs/requirements-map.md`.
- Mock tests validate logic only. They are never evidence of live integration (source download, real-device posting). If external access is missing, mark the check `No / not tested` and say exactly what is needed.
- Default to local/staging, `POSTING_MODE=dry_run`, and the sandbox billing provider. Do not post publicly, make payments, or deploy to production to demonstrate a gate. Do not add a `live-post` command that is enabled only by an env file.
- Gate records (`docs/gates/Gn.md`) follow the template in PRD §J. Never invent an approver or a sign-off. `make check-gate` must check evidence links, not task checkboxes.
- After each coherent slice, update `docs/progress.md` using the template in PRD §K. Report with the main result first, then a Phase / Gate Yes/No / Evidence / Next step table.
- Record user decisions that override the PRD in `docs/decisions.md`. Open product decisions are D01–D07.
- Do not store credentials in source, logs, URLs, reports or committed fixtures.

## Planned stack and layout (PRD §B, §C)

Web: React + TypeScript + Vite (`apps/web/`). API: Python FastAPI (`services/api/`). Separate `services/worker/` (render) and `services/scheduler/`. PostgreSQL with SQLAlchemy and Alembic. Redis queue (pick the worker framework in P0 and record it). FFmpeg and yt-dlp sit behind adapters. S3-compatible storage has a local adapter. `agent/` is a Python Windows Agent. `packages/contracts/` holds API types *generated* from the API, never handwritten duplicates. Docker Compose runs the local services. Pin versions in lockfiles and record tested combinations in `docs/compatibility.md`.

## Commands

```
py tasks.py setup                        # create .venv, pip install -e services/worker + pytest
py tasks.py test-unit                    # tests/unit + services/worker/tests (uses .venv)
.venv/Scripts/python -m pytest services/worker/tests/test_poc_units.py::test_name   # single test
py tasks.py check-gate <n>               # validate docs/gates/Gn.md: 0 passed, 1 not passed, 2 invalid record
docker compose up -d                     # local Postgres/Redis/MinIO (Docker Desktop must be running)

# P1 POC (run from the repo root with PYTHONPATH=services/worker, or after setup)
.venv/Scripts/python -m clipflow_worker.poc inspect <url>...
.venv/Scripts/python -m clipflow_worker.poc produce <url> --clips 3 --seed 42 --max-duration 14400   # -> var/poc/<src>/manifest.json
.venv/Scripts/python -m agent.cli devices | doctor --serial S | dry-run --serial S --file clip.mp4   # stops before any TikTok UI
```

Rules for gates and commands:
- `check-gate` never derives Yes from checkboxes. A Yes row must cite existing repo paths in backticks, and a sign-off needs a named approver. Never write an approver yourself.
- Unimplemented `tasks.py` targets (`lint`, `typecheck`, `build`, `dev`, `migrate`, …) exit 3 on purpose.
- Never add a live-post command.

Environment notes:
- Python 3.14 runs on the host.
- FFmpeg 9 comes from winget. `media.binary()` resolves the winget symlink, and `ensure_on_path()` must run before the first yt-dlp call, because yt-dlp caches ffmpeg detection per process.
- yt-dlp uses Node as its JS runtime for YouTube.
- The console uses cp874, so CLIs that print Thai must reconfigure stdout to UTF-8.

## Architecture: the parts that span modules

**Pipeline:** Web UI → API → DB/quota ledger → render queue/worker → object storage → scheduler → per-device queue → customer Agent (outbound HTTPS polling only, no exposed ADB) → Android → result verification.

**Identity chain:** Workspace → Username + Agent Token → server-bound Environment → Agent installation/session → Android serial → expected TikTok account.
- Browser auth and Agent auth are separate.
- The Environment scope comes from the token on the server, never from a client claim.
- Tokens are stored as public prefix + hash. The secret is shown once.
- Reconnecting the same `installation_id` does not count as a new registration.
- Server-side session fencing (lease owner, generation, expiry) makes stale Agents lose their claims.

**State machines:**
- Job: RECEIVED → SOURCE_VALIDATED → DOWNLOADING → ANALYZING → RENDERING → READY_FOR_REVIEW → APPROVED → SCHEDULED. Failures go to NEEDS_ACTION, FAILED or CANCELLED.
- Publish: SCHEDULED → CLAIMED → TRANSFERRING → PREPARING → SUBMITTING → VERIFYING → VERIFIED_SUCCESS. Other outcomes are RETRYABLE_FAILED, UNKNOWN, NEEDS_ACTION, SKIPPED and CANCELLED.

**Invariants to preserve (PRD §F, §H):**
- Every tenant row has `workspace_id`, and every resource and file access is ownership-checked on the server.
- Quota ledger: integer units, unique idempotency keys, and an auditable reserve → settle/refund trail. Repeated events must not double-charge or double-refund.
- Environment and device caps are enforced in transactions, as plan-wide aggregates. Adding Environments does not multiply plan entitlements.
- A device serial is never proof of ownership, and a binding conflict is never silently moved.
- A schedule item references a specific approved render/metadata version, never "latest". Changing rendered text means a new render. Editing metadata bumps its version and re-triggers the review policy.
- If an Agent is lost after SUBMITTING, the attempt becomes **UNKNOWN** and needs audited reconciliation. Never blindly retry. Tapping Post or a successful ADB command is not success; verification has to tie the post to the account and the clip.
- Payment events are unique per (provider, event_id). Amount, currency and plan version are always computed on the server.

**Scheduling (PRD §G, §5):**
- Each next slot is the previous *scheduled* slot + X hours, pushed forward into the allowed window. It is never based on the actual publish time.
- MVP windows are same-day only. Asia/Bangkok must reproduce the PRD examples, e.g. 19:00, N=3, X=2, window 09–21 → 19:00, then 09:00 and 11:00 the next day.
- Posting runs in parallel across devices up to the plan's limits, but claims are serialized per device: a same-device collision is queued to start when the device is free, not rejected (Q-05/Q-06).
- Offline, pause/resume and reboot never cause a catch-up burst. Each item stores scheduled, claimed, started, submitted and verified timestamps separately.
- The preview is calculated on the server, not in the browser.

**Security:** follow the source allowlist and add SSRF checks on redirects and adapter-returned media URLs. Render workers run with resource limits. The Agent never receives server DB, storage or billing credentials. Never strip watermarks or alter footage to evade platform originality checks.
