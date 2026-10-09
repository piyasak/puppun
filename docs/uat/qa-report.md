# Consolidated QA report — G7-04 (load, security, Thai, mobile, accessibility)

Date: 2026-10-09. Build: branch `p3-jobs-and-clips` after `8ae381f`, plus the changes listed below. Machine: the Windows 11 QA PC.
- Browser: Edge (Playwright).
- Services: Postgres 16 from compose and local Supabase.
- Phone: QA phone POCO 25078PC3EG (D03).

This is a pre-pilot report. Pilot data (real users, real devices, real networks) is still needed for G7-01, G7-02 and G7-05.

## Result

| Area | NF | Result | Evidence | Gaps |
|---|---|---|---|---|
| API load | NF-04 | **Pass**, two runs. Run 1: 3,596 requests; p50 167 ms; **p95 629 ms**; max 1.1 s. Run 2: 3,447 requests; p50 233 ms; **p95 741 ms**; max 1.4 s. Both: 50 concurrent users for 60 s, 0 server errors, every endpoint p95 < 1 s. One API worker | `services/api/tests/test_crud_load.py`, `services/api/tests/load_client.py` (opt-in, `CLIPFLOW_LOAD=1`) | Little margin on one worker. Production should run several workers; re-measure on staging (G2-05) |
| Dispatch load | NF-05 | **Pass** (G4-05): 150 phones / 300 posts; p95 dispatch latency 14.3 s, all within 60 s; claim p95 77 ms | `services/api/tests/test_dispatch_load.py` | — |
| Tenant isolation | NF-01 | **Pass**: every route that takes an id answers another tenant exactly like a missing id; media needs a signature (T01) | `services/api/tests/test_uat.py`, `services/api/tests/test_tenant_isolation.py` | — |
| Credentials | NF-02 | **Pass**: Agent tokens are 256-bit, stored as hashes and never logged; browser tokens are accepted only in the header; the Agent token is stored with DPAPI | `services/api/tests/test_agent_tokens.py`, `services/api/tests/test_auth.py`, `agent/credentials.py` | Code signing of the Agent exe before release (G5) |
| URL / SSRF / render limits | NF-03 | **Pass** (T08): redirects to private addresses are refused through yt-dlp; ffmpeg media URLs are checked; renders have a timeout and capped threads | `services/worker/tests/test_netguard.py` | — |
| Dependencies | — | `npm audit --omit=dev`: 0 vulnerabilities. `pip-audit` on the project venv: no known vulnerabilities (our own two packages are not on PyPI and are skipped) | `apps/web/package-lock.json` | Add both audits to CI |
| Thai | NF-09 | **Pass**: Thai UI, `lang="th"` on every page, Thai email templates (sent through Gmail SMTP on the cloud project). Caption with Thai, emoji and hashtags matched character for character on the real phone (T16) | `apps/web/e2e/quality.spec.ts`, `supabase/templates/confirmation.html`, `tests/unit/test_tiktok_ui.py` | — |
| Mobile 360 px and 200 % zoom | NF-09 | **Pass**: 15 page states × 3 sizes (360×780, 640×400 = 1280×800 at 200 %, 1280×800) with real data, including long Thai names. No page scrolls sideways (detector checked against a deliberately wide element) | `apps/web/e2e/quality.spec.ts` (screenshots in `var/evidence/e2e/quality/`, not committed) | 200 % zoom is simulated by the CSS viewport; no real phone browser tested |
| Accessibility (automated) | NF-09 | **Pass**: axe-core 4.13 WCAG 2.0/2.1 A + AA rules on all 15 page states, 0 violations | `apps/web/e2e/quality.spec.ts` | Automated rules catch only part of WCAG; there has been no screen reader (NVDA) pass and no manual review |
| Keyboard and focus | NF-09 | **Pass, after a fix**: sign-in, plus a keyboard-only journey: create job (radio, select, number) → approve → preview → schedule → confirm dialog (focus moves in, Esc closes and gives focus back, Enter confirms). Focus is visible at every Tab stop. **Found + fixed:** the date-time inputs (schedule start, edit time) showed no focus ring, because Chromium focuses an inner segment that `:focus-visible` misses. There is now a global focus rule, with `:focus-within` for date/time inputs | `apps/web/e2e/quality.spec.ts`, `apps/web/src/index.css` | — |

## Pages covered by the NF-09 sweep

Public pages: `/login`, `/signup`, `/forgot` and `/auth/confirm`.

Signed-in pages, with a named phone and a job whose clip is approved and scheduled: `/`, `/environments`, `/agent-tokens`, `/agents`, `/devices`, `/create`, `/jobs`, `/jobs/:id`, `/schedule` (week and list) and `/billing`.

`/admin` is covered by `admin.spec.ts` at desktop size only.

## Decision input for G7-04

Every automated check passes, after one defect was found and fixed (focus on date-time inputs, Medium). G7-04 stays **No** until these are done:
1. A manual accessibility pass with a screen reader (NVDA).
2. A real phone browser at 360 px.
3. The load test repeated on staging (G2-05).
