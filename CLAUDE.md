# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

G0, G3, G4 and G5 are Yes (signed off). G1 is No: 5/6, with G1-06 cost deferred. G2 is No (3/5): no release or pilot. G6 is No (3/5) but PO-signed under Q-31 (sandbox billing only, no real payments). P7 has started with the local T01–T25 regression (`docs/uat/p7-uat.md`); P2-P4 were started under PO overrides Q-22/Q-24/Q-26. Real posts happen only under a recorded one-post PO grant (Q-29/Q-30 are used up). Clips are 3–5 minutes (D02). The QA machine is this PC, with one phone model (POCO 25078PC3EG). What exists:
- `PRD_CLAUDE_CODE.md`: the product source of truth. Sections A–N are the implementation contract; section O is the full Thai PRD with the 47 gate checks and UAT cases. The `.docx` is the original and duplicates section O.
- `docs/`: progress (read first), architecture, decisions (D/Q/E registers, including PO answers from 2026-10-06), requirements-map, ui-map, backlog, compatibility (real source/device results), and `gates/G0–G8.md`.
- `services/worker/clipflow_worker/`: the P1 media POC.
  - `source.py`: yt-dlp adapter with a URL allowlist, an SSRF guard on media URLs, and error classification.
  - `segments.py`: audio-pause boundaries plus seeded selection.
  - `textlayout.py`: Thai-safe line wrapping.
  - `render.py`: 9:16 output via libass/.ass.
  - `poc.py`: the CLI.
- `services/api/clipflow_api/`: the P2 API (FastAPI). Browser identity is Supabase Auth (E-27, project `punpun`, see `docs/runbooks/supabase-auth.md`). `identity.py` verifies the Bearer access token against the JWKS: ES256/RS256 only, public keys only. It also has `POST /v1/onboarding` (username + Workspace + rights acceptance + demo plan), `/v1/me`, `/v1/workspace/usage`, Environments whose limits are allocations of the plan caps (`entitlements.py`, checked under the subscription row lock), Agent tokens (`agent_tokens.py`: `cfat_<prefix>_<secret>`, stored as prefix + SHA-256 and shown once; parse tokens with `TOKEN_RE`, never `split('_')`), Alembic migrations in `services/api/migrations/`, and integration tests in `services/api/tests/` that run against a throwaway Postgres database. Schedules (P4, E-39): `slots.py` is the only place slot times are calculated (pure, UTC + IANA zone, Asia/Bangkok only); `schedules.py` builds the preview, creates series/items bound to the approved (metadata version, sha256), parks items when approval changes (`sync_clip_items`) and has `dispatchable`, the last check before any post is handed to an Agent. Tenant scoping goes through `tenancy.py` (`scoped`/`get_owned`), and cross-tenant access returns the same 404 as a missing row.
- `apps/web/`: React + TS + Vite web app. It has Thai auth screens (signup, login, forgot, reset), onboarding, a dashboard shell, Environments/Agent tokens/Agents/phones, and the P3 job screens (`/create` wizard, `/jobs`, `/jobs/:id` with preview, caption/hashtag edits and approval; shapes and Thai wording in `src/lib/jobs.ts`). Supabase settings come from `.env*.local` (gitignored, public values only). Playwright journeys live in `apps/web/e2e/` and must only target the local Supabase (`supabase/config.toml`).
- `agent/`: the Agent. It has an ADB adapter, a write-ahead attempt journal (`attempt.py`), the server client (`server_client.py`: sign-in, heartbeat, phones, jobs, clip upload), the phone check (`device_registry.py`, Q-25) and the job runner (`job_runner.py`, E-37). The job runner claims a job, runs the P1 pipeline (`services/worker/clipflow_worker/pipeline.py`) and uploads clips; it keeps rendered clips under `<data dir>/clips/<job id>/` for posting later. The post runner (`post_runner.py`, E-42) claims due posts, gets the bound file (own copy or verified download), pushes it with an on-phone hash check, waits for the Gallery and stops before Submit (dry-run only). `tiktok_ui.py` (Q-27) goes through TikTok up to, never including, Post: it has no Post/Story/Draft/Shop press and re-reads the screen before every press.
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
py tasks.py setup                        # create .venv, pip install -e services/worker + services/api[test] + pytest
py tasks.py test-unit                    # tests/unit + services/worker/tests (uses .venv)
.venv/Scripts/python -m pytest services/worker/tests/test_poc_units.py::test_name   # single test
py tasks.py check-gate <n>               # validate docs/gates/Gn.md: 0 passed, 1 not passed, 2 invalid record
py tasks.py lint | typecheck | build     # ruff + oxlint | tsc | web build (build needs the VITE_ vars); CI: .github/workflows/ci.yml
docker compose up -d                     # local Postgres/Redis/MinIO (Docker Desktop must be running)
py tasks.py migrate [alembic args]       # default: upgrade head on DATABASE_URL or the local compose DB
py tasks.py test-integration             # services/api/tests on a throwaway DB (skips if Postgres is down; a skip is not evidence)
npx supabase start -x studio,storage-api,imgproxy,realtime,edge-runtime,logflare,vector,supavisor,postgres-meta   # local auth + Mailpit
py tasks.py test-e2e                     # Playwright (apps/web/e2e, Edge) on LOCAL Supabase + fresh clipflow_e2e DB
cd apps/web && npm run build             # needs VITE_SUPABASE_URL/_PUBLISHABLE_KEY/VITE_API_URL; tsc + vite build + bundle check (E-32); `npm run lint` = oxlint
.venv/Scripts/python -m uvicorn clipflow_api.app:app --port 8000   # needs DATABASE_URL and SUPABASE_URL

# P1 POC (run from the repo root with PYTHONPATH=services/worker, or after setup)
.venv/Scripts/python -m clipflow_worker.poc inspect <url>...
.venv/Scripts/python -m clipflow_worker.poc produce <url> --clips 3 --seed 42   # 3-5 min clips -> var/poc/<src>/manifest.json
.venv/Scripts/python -m clipflow_worker.poc produce --file <customer video> [--captions x.srt]
.venv/Scripts/python -m agent.cli devices | doctor --serial S | dry-run --serial S --file clip.mp4   # stops before any TikTok UI
.venv/Scripts/python -m agent.cli connect --server http://127.0.0.1:8000 --username U --seconds 60 [--media-dir D]   # token from CLIPFLOW_AGENT_TOKEN or prompt, never argv; checks/registers phones on start and every 60 s (Q-25, --no-phone-check); claims and makes clip jobs one at a time (P3.3, --no-jobs)
CLIPFLOW_REAL_SOURCE_URL=<corpus url> .venv/Scripts/python -m pytest services/api/tests/test_real_source_job.py   # opt-in, network: real source through the job runner
.venv/Scripts/python -m agent.cli register-devices --server http://127.0.0.1:8000 --username U       # registers ready phones by ro.serialno
CLIPFLOW_REAL_DEVICE=1 .venv/Scripts/python -m pytest services/api/tests/test_real_device_registration.py   # opt-in, phone on USB
CLIPFLOW_REAL_DEVICE=1 .venv/Scripts/python -m pytest services/api/tests/test_real_device_post.py -s   # opt-in: dry-run post on the QA phone (push, hash, Gallery, removed; TikTok never opened)
CLIPFLOW_LOAD=1 .venv/Scripts/python -m pytest services/api/tests/test_dispatch_load.py -s   # opt-in, ~5 min: 150 phones / 300 posts, p95 dispatch latency (G4-05)
.venv/Scripts/python tools/build_agent.py [version]          # PyInstaller bundle -> var/dist/punpun-agent-<v>.zip (+ .sha256), E-44
.venv/Scripts/python -m agent install --bundle B --sha256 H  # install/update (refused while a post is between Submit and its result); rollback | login | status | version
CLIPFLOW_AGENT_BUNDLE=1 .venv/Scripts/python -m pytest tests/test_agent_bundle.py   # opt-in: packaged exe install -> self-update -> rollback
CLIPFLOW_AUTHORIZED_POST=<decision> .venv/Scripts/python -m pytest services/api/tests/test_authorized_real_post.py -s   # ONLY with a recorded PO grant (Q-29 is used up); one real post
.venv/Scripts/python -m agent.cli ui-rehearsal --serial S --file clip.mp4 --caption "..." --account HANDLE   # Q-27: TikTok steps up to Post on the QA phone, never presses Post, force-stops TikTok
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

**Pipeline (Q-15 ข2):** Web UI → API → DB/quota ledger → scheduler → customer Agent (outbound HTTPS polling only, no exposed ADB). The Agent downloads or reads the customer's own file, analyzes and renders on the customer machine, then uploads the finished clip + sha256 for preview/approval. Later it posts that same local file to Android and verifies the result. Sources: YouTube, Bilibili, customer-provided file (Q-17). Download bot checks are `SOURCE_RATE_LIMITED` with a per-platform cool-down; never rotate IPs or use proxies to get around them.

**Identity chain:** Workspace → Username + Agent Token → server-bound Environment → Agent installation/session → Android serial → expected TikTok account.
- Browser auth (Supabase Auth JWT in `Authorization: Bearer`, never cookies or query strings) and Agent auth (our own tokens, P2.4/P2.5) are separate. Never create accounts on the real Supabase project yourself; the PO runs live sign-up tests.
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
