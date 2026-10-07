# ClipFlow — PRD for Claude Code

Version: 1.1 • Date: 2026-10-06 • Product language: Thai • Development documentation: Thai or English

This is a self-contained implementation specification. It includes the product PRD, phase plan, 47 Yes/No gate checks, and the execution contract below. Read the complete document before changing code. The user is requesting this development brief; no production implementation or gate has passed merely because this file exists.

## A. Start here

Build ClipFlow: a monthly subscription web service that converts one authorized YouTube/Bilibili source into multiple vertical clips, generates editable Title/Ending/Caption/Hashtag, and schedules those clips every X hours to a registered Android device through a customer-installed Windows Agent.

Required identity chain: Workspace owner → Username + generated Agent Token → server-bound Environment → registered Agent installation/session → authorized Android Serial → expected TikTok account.

### Initial instruction for Claude Code

```text
Read PRD_CLAUDE_CODE.md completely. Inspect the existing repository and its
instructions before making changes. Use this PRD as the product source of truth.

First implement Phase 0 deliverables: repository assessment, requirement map,
decision register, backlog, and gate register. Then implement the Phase 1 POC
within the approved scope. Use real evidence for each gate; never treat a mock,
unexecuted test, or generated screenshot as evidence of working integration.

For each phase, implement the smallest end-to-end slice, run the relevant
checks, record evidence, and report Check Gate: Yes/No with the reason.
Continue routine work that is already authorized. Stop dependent implementation
at a failed prerequisite gate. Ask only for a concrete missing decision,
credential, device access, or sign-off that is genuinely required.

Default to local/staging and dry-run Android posting. Do not make payments,
post publicly, or deploy production merely to demonstrate a gate. Use a
separately authorized account, device, and test environment for live evidence.

Keep docs/progress.md up to date so work can resume in a new session. Do not
invent successful test results or silently replace a requested feature with
a simulation. If external access is unavailable, mark that check No with
reason "not tested", keep its interface and isolated tests, and identify
exactly what is needed to complete it.
```

Place this file at the repository root as `PRD_CLAUDE_CODE.md`. The Bootstrap instruction above can be pasted directly into Claude Code. Do not execute the entire 12-week plan as an unreviewed one-shot change.

## B. Implementation decisions and precedence

1. Explicit user changes override this version. Record them in `docs/decisions.md` and update affected acceptance criteria.
2. Preserve existing repository architecture unless it cannot meet a requirement. For a new repository use the reference stack below.
3. Sections A–N add implementation detail to the full product PRD in section O. Where a proposal narrows or conflicts with the original scope, record a decision rather than silently changing the requirement.
4. Proposed prices, versions, service providers, capacity targets and schedule estimates are not approved commercial commitments.
5. No public deployment or actual posting is implied by this document. Preparation, local implementation, reversible tests and staging work can proceed within the user's task authorization.
6. One failed required check means the gate is No. A technical pass and a human commercial/release approval are separate fields.

### Reference stack for an empty repository

| Layer | Default implementation direction |
|---|---|
| Web | React + TypeScript + Vite; reusable accessible components; Thai UI |
| API | Python + FastAPI; validated request/response models |
| DB | PostgreSQL + SQLAlchemy + Alembic migrations |
| Queue | Redis + a durable retry-aware worker framework selected and recorded in P0 |
| Media | FFmpeg/FFprobe; source adapters around yt-dlp; transcript/LLM adapters |
| Agent | Python on Windows; ADB/UIAutomator2 behind adapters; local status UI |
| Files | S3-compatible object storage; local development adapter |
| Billing | Provider-neutral adapter; sandbox first; provider selection is a decision |
| Checks | pytest for backend/Agent, web typecheck/lint/build, browser E2E for critical journeys |
| Local runtime | Docker Compose for API/DB/Redis/storage/workers; Web dev server |

Resolve dependency versions from current primary documentation when developing, pin them in lockfiles, and record the tested compatibility matrix. Do not assume the newest version is compatible with every Android device. Do not introduce additional vendors or paid API dependencies without a product need.

## C. Repository structure to create

```text
PRD_CLAUDE_CODE.md
CLAUDE.md
README.md
.env.example
.gitignore
Makefile
docker-compose.yml
apps/web/
services/api/
services/worker/
services/scheduler/
agent/
packages/contracts/
tests/integration/
tests/e2e/
tests/fixtures/
docs/architecture.md
docs/decisions.md
docs/backlog.md
docs/progress.md
docs/requirements-map.md
docs/compatibility.md
docs/gates/G0.md ... G8.md
docs/runbooks/
```

`packages/contracts` holds generated API types or versioned schemas, not independently handwritten duplicate contracts. Tests use authorized fixtures and synthetic data; credentials, personal footage, full mobile screenshots and large videos are not committed to Git.

### CLAUDE.md content to create

```markdown
# ClipFlow execution rules
- Read PRD_CLAUDE_CODE.md and docs/progress.md before starting a new task.
- Keep scope and FR/NF/Gate IDs traceable in docs/requirements-map.md.
- Work in phase order; No gates block dependent production work.
- Mock tests validate logic only, never live integration feasibility.
- Preserve tenant isolation, token secrecy, quota idempotency and device locks.
- A post with unknown result cannot be submitted again without reconciliation.
- Do not store credentials in source, logs, URLs or reports.
- Use local/staging and dry-run by default. Live posting/payment/release needs
  the applicable authorization and valid access, not a made-up test result.
- Run checks appropriate to the change and record actual commands/results.
- Keep progress, blockers, decisions and next actions current.
- Do not claim completion while a required gate lacks evidence.
```

## D. Implementation backlog by phase

### P0 — Scope and repository baseline

- [ ] P0.1 Inspect the repository, discover existing instructions, and report what can be reused.
- [ ] P0.2 Create requirement-to-module/test/gate mapping for FR-01–24 and NF-01–10.
- [ ] P0.3 Create all gate records with No / not tested initially.
- [ ] P0.4 Map all UI routes and journeys, including empty/loading/error/success states.
- [ ] P0.5 Record open product decisions D01–D07 with owners; distinguish reversible engineering choices from commercial decisions.
- [ ] P0.6 Create prioritized backlog, resource estimate, and authorized fixture/device plan.

Definition of done: Gate 0 criteria have evidence or explicit blockers; P0 documentation is reviewable. An approved scope must not be replaced by an agent's own sign-off.

### P1 — Feasibility POC before full SaaS implementation

- [ ] P1.1 Create CLI adapters that inspect/download an authorized source and extract metadata.
- [ ] P1.2 Record results for at least 5 authorized links from each requested source, documenting unsupported variants.
- [ ] P1.3 Render multiple 9:16 clips with Thai text from a fixture and validate media properties.
- [ ] P1.4 Implement ADB connection, file transfer, Gallery discovery and Unicode input POC.
- [ ] P1.5 Execute an authorized posting/verification test on at least two supported Android models, or mark the hardware checks No / not tested.
- [ ] P1.6 Inject disconnect before/after Submit and show safe UNKNOWN behavior.
- [ ] P1.7 Record service/source requirements review, compatibility matrix, runtime and cost measurements.

No Gate 1 Yes without actual source and device evidence. An emulator or mock may support local tests but does not substitute for the required real-device matrix.

### P2 — SaaS and identity foundation

- [ ] P2.1 Build Auth/Workspace and migration baseline.
- [ ] P2.2 Apply server-side ownership checks to every resource and file access path.
- [ ] P2.3 Implement Environment and separate registration/session limits, including plan-wide aggregate limits.
- [ ] P2.4 Implement Generate/one-time Copy/Expire/Revoke/Rotate Token and scope checks.
- [ ] P2.5 Register installations, reconnect without extra registration, heartbeat and fence duplicate sessions.
- [ ] P2.6 Register device Serial through the Agent; handle offline/unauthorized ownership conflicts.
- [ ] P2.7 Create Dashboard/Connection/Devices/Settings working UI and staging CI checks.

### P3 — Video pipeline and review

- [ ] P3.1 Validate and retrieve sources with size/duration/redirect/resource limits.
- [ ] P3.2 Build transcript/segment selection and seeded random selection of eligible segments.
- [ ] P3.3 Render Title/Ending/Subtitles using versioned templates; generate editable metadata.
- [ ] P3.4 Reserve quota, render clips, settle/refund ledger entries safely on repeated events.
- [ ] P3.5 Implement Create wizard, Jobs list and actual media preview/detail/approval UI.
- [ ] P3.6 Support review/auto modes, insufficient-source-content flow, cancellation and errors.

### P4 — Scheduler

- [ ] P4.1 Implement server-calculated series/items with interval, window and timezone.
- [ ] P4.2 Show a server-derived preview; do not rely on separate browser-only scheduling logic.
- [ ] P4.3 Implement collision detection, device serialization and claim locking.
- [ ] P4.4 Implement pause/resume/edit/cancel and offline skip/defer with no catch-up burst.
- [ ] P4.5 Record timestamp distinctions and verify restart/redelivery behavior.
- [ ] P4.6 Build list/week calendar UI, item detail, conflict explanation and load checks.

### P5 — Customer Agent and posting

- [ ] P5.1 Package Windows Agent with configuration, credential storage, connection/device/job status and local logs.
- [ ] P5.2 Implement authenticated outbound claim/download/result APIs with session generation and device lease checks.
- [ ] P5.3 Check downloaded hash, transfer media, locate the correct file and verify the expected TikTok account.
- [ ] P5.4 Execute UI state transitions and Thai metadata input; stop on unknown UI/login/CAPTCHA.
- [ ] P5.5 Record publish attempts and reconcile ambiguous outcomes without blind retry.
- [ ] P5.6 Add installer/update/rollback and compatibility rejection; avoid updates during Submit.
- [ ] P5.7 Run fault tests and authorized real-device evidence; build needs-action resolution UI.

### P6 — Billing and Admin

- [ ] P6.1 Finalize provider/commercial policy; keep one sandbox adapter as the initial implementation.
- [ ] P6.2 Implement payment requests, signed webhook validation and event deduplication.
- [ ] P6.3 Implement subscription expiry/renewal and atomic quota cycle boundaries.
- [ ] P6.4 Build Plans/Checkout/Pending/History and Admin Users/Plans/Jobs/Payments UI.
- [ ] P6.5 Record plan version, effective date, audit reasons and support permissions.
- [ ] P6.6 Implement retention and deletion lifecycle without deleting active job inputs.
- [ ] P6.7 Measure unit economics and approve actual pricing before real paid enrollment.

### P7 — Pilot/UAT

- [ ] P7.1 Run T01–T25 from the full PRD plus regressions for all required gates.
- [ ] P7.2 Onboard at least 10 new users and record time/success/blockers.
- [ ] P7.3 Record at least 50 eligible production tests and 50 authorized posting tests.
- [ ] P7.4 Report success/failed/unknown separately; no dropping failed eligible attempts to improve results.
- [ ] P7.5 Verify tenant/security/load/responsive/Thai and cost/support targets.
- [ ] P7.6 Resolve Critical/High defects and obtain Pilot sign-off.

### P8 — Launch readiness

- [ ] P8.1 Prepare production configuration and staged capacity limits.
- [ ] P8.2 Perform restore/reconciliation drill and document RPO/RTO.
- [ ] P8.3 Exercise separate kill switches and rollback without losing external attempt state.
- [ ] P8.4 Complete support, incident, compatibility and commercial runbooks.
- [ ] P8.5 Record release approver and cohort; deploy only when the applicable release authorization is present.

## E. API contract baseline

All routes below are design contracts to implement, not existing endpoints. Prefix `/v1`; UUID resource IDs; structured errors with `code`, `message`, `request_id` and optional safe details. Timestamps use timezone-aware ISO 8601; storage uses UTC. Return only public fields and enforce tenant scope on Server.

| Method | Endpoint | Behavior / important rule |
|---|---|---|
| POST | /auth/register, /auth/login | Create/enter Workspace; secure web session |
| POST | /auth/password-reset/request, /confirm | Single-use expiring reset; no account enumeration |
| GET | /me, /workspace/usage | Profile, subscription and authoritative quota |
| POST/GET | /jobs | Idempotent job creation and scoped list |
| GET | /jobs/{id} | Job status, clips, source and safe cost/usage details |
| POST | /jobs/{id}/cancel | Phase-aware cancellation |
| PATCH | /clips/{id}/metadata | Editable text with expected version check |
| POST | /clips/{id}/approve | Approve a specific render/metadata version |
| GET | /clips/{id}/media | Short-lived authorized media access |
| POST/GET/PATCH | /templates, /templates/{id} | Versioned owned templates |
| POST | /schedules/preview | Validate and calculate proposed items without publishing |
| POST/GET | /schedules | Series create/list; idempotency on create |
| POST | /schedules/{id}/pause, /resume | Recalculate remaining items without catch-up burst |
| PATCH/POST | /schedule-items/{id}, /{id}/cancel | Version/claim boundary checks |
| POST/GET/PATCH | /environments, /environments/{id} | Limits must fit subscription and aggregate plan caps |
| POST/GET | /agent-tokens | Secret returned once on creation; list never returns secret |
| POST | /agent-tokens/{id}/revoke | Revoke relevant sessions; audit without secret |
| POST | /agent/authenticate | Username + Token + installation_id → scoped short-lived session |
| POST | /agent/heartbeat | Current session generation and device readiness |
| POST | /agent/devices/register | Server checks ownership and plan device cap |
| POST | /agent/jobs/claim | Atomic claim; enforce active session and device lock |
| POST | /agent/attempts/{id}/events | Ordered versioned event reporting; deduplicate event IDs |
| POST | /publish-attempts/{id}/resolve | Audited reconciliation; proof required for success/retry decision |
| GET/PATCH/POST | /devices, /devices/{id}, /{id}/unbind | Scoped registered devices; outstanding work handled explicitly |
| GET/POST | /billing/plans, /billing/checkout | Server calculates amount from plan version |
| POST | /billing/webhooks/{provider} | Verify raw payload signature; provider event deduplication |
| GET | /billing/subscription, /payments | Current entitlements and payment history |
| GET/PATCH | /admin/users, /plans, /jobs, /payments | Explicit admin permission and audit |

Browser auth and Agent auth are separate. Never let an Agent token act as unrestricted web-admin access. Agent APIs return only jobs/devices in their scope. Do not place secrets in query parameters. A WebSocket is not required for MVP; authenticated outbound polling is acceptable.

## F. Critical schema invariants

- Every tenant-owned row has `workspace_id`; validate all foreign-resource relationships within that tenant.
- Agent tokens have a public ID/prefix and secret hash; raw secret only appears in the creation response and customer credential storage.
- Environment quotas are enforced transactionally across simultaneous registrations, not only in UI.
- Sum of active registrations and device entitlements across Environments must respect plan-wide caps. Creating more Environments cannot multiply subscription rights.
- A device serial is normalized and never trusted as proof of ownership. Active serial binding conflicts require explicit ownership resolution; do not silently move it.
- A clip stores source interval, seeded selection, template version, render hash, metadata version and approved version.
- Changes to rendered text require a new render; changes that affect approval invalidate relevant approval. Editing Caption changes metadata version and requires the configured review policy before posting.
- A scheduled item references a specific approved/render-ready clip version. Do not select "latest clip" at dispatch without checking approval.
- Ledger reference/idempotency keys are unique. Reservation/settlement/refund events form an auditable transaction trail; use integer units, not floating balance arithmetic.
- Payment events are unique by provider + event ID. Amount/currency/plan version are server-authoritative.
- Claim transitions have lease owner, generation, expiry and state version. Stale agents cannot continue via accepted server events after losing their lease.
- There is no safe external UI-submit transaction with the DB. Expiry after Submit enters UNKNOWN and reconciliation, not automatic replay.

## G. Scheduling implementation algorithm

1. Validate integer `interval_hours >= 1`, `clip_count > 0`, timezone, start time and supported window. For MVP use same-day windows only; reject end <= start. `24:00` means day end, not a parsable local time value.
2. Obtain eligible clip versions in a stable order.
3. Normalize the first proposed slot to the next allowed local window if necessary.
4. For each subsequent clip propose previous scheduled slot + X elapsed hours; normalize forward into its timezone's next allowed window.
5. Preview must show timestamps, timezone, device, clip version and collisions. Saving reruns validation transactionally.
6. Serialize claims per device. Apply readiness/subscription/approval/session/lease checks immediately before dispatch and again before submission.
7. Defer policy preserves clip order and spacing by moving affected unstarted items forward. Skip policy skips that item without assigning its clip to an immediate burst.
8. Never derive the next slot from the previous verified publish time. Store scheduled/claimed/started/submitted/verified timestamps independently.
9. Do not run overdue items immediately on reboot. Reconcile attempts first, then apply offline/resume policy to remaining unstarted items.

Asia/Bangkok must pass the examples in the original PRD. If other IANA timezones are selectable, define DST ambiguous/nonexistent time handling and test it; otherwise restrict the MVP selector to the supported timezone and state that limit.

## H. Verification and retry contract

Publishing success requires a verifiable result associated with the correct account and intended clip: provider/platform identifier when accessible, or a documented verification method validated in P1/P5. A tap on Post, a disappearing dialog, or successful ADB command alone is not success.

If verification cannot confidently associate the published content with the attempt, state is UNKNOWN. The user/support resolution must record evidence and choice: found published → verified; confirmed not published → eligible retry; still unknown → remain paused. UI must never preselect a risky retry conclusion.

Use mock Android adapters to test transitions, not to claim real posting compatibility. Do not strip watermarks or alter footage to evade platform originality checks. Random selection is for editing variety within authorized content.

## I. Test and developer command contract

Create these commands as part of the repository scaffolding. They are planned command names, not claims that a project already exists. On Windows provide equivalent PowerShell/Python task entry points where `make` is not available.

```bash
make setup           # install locked dependencies and validate local prerequisites
make dev             # start local services; never production by default
make migrate         # apply development migrations
make seed-demo       # synthetic data; never overwrite customer data
make lint
make typecheck
make test-unit
make test-integration
make test-e2e        # web/adapter critical journeys
make build
make smoke
make check-gate PHASE=0
```

Use a separate, explicit authorized real-device invocation such as:

```bash
python -m agent.cli doctor --serial <registered-serial>
python -m agent.cli dry-run --job <test-job-id>
```

Do not add a `live-post` command that silently enables posting based only on a generic environment file. If implemented, it must require current account/device/scope checks and applicable authorization. Never publish secrets or fixture cookies in test evidence.

Tests must verify important behavior independently: tenant access denial, atomic quotas, payment deduplication, schedule window boundaries, session fencing and disconnect after Submit. Do not add tests that merely duplicate private implementation logic.

## J. Evidence-based gate record

For every `docs/gates/Gn.md`, use this format:

```markdown
# Gate Gn
Phase: Pn
Build/commit: <actual reference>
Environment: <actual environment>
Reviewed at: <timestamp>

| Check ID | Yes/No | Reason | Evidence | Owner | Due date |
|---|---|---|---|---|---|
| Gn-01 | No | Not tested | — | <owner> | <date or TBD> |

Technical required checks all Yes: No
Required human sign-off recorded: No
Phase gate decision: No
Next phase allowed: No
Blockers: <concrete missing evidence or decision>
Approver: <real reviewer, never invented>
```

The 47 checks are in the full PRD below. A command with an exit code of zero establishes only what that test actually checks. `make check-gate` must validate complete evidence links and required sign-offs; it must not mark Yes based solely on phase task checkboxes. Do not manufacture an approval signature.

## K. Session handoff and status output

Update `docs/progress.md` after each coherent slice:

```markdown
Current phase:
Implemented:
Changed files/modules:
Commands run and actual results:
FR/NF/Gate IDs covered:
Checks passed:
Checks No — failed:
Checks No — not tested / blocked:
Open decisions:
Next concrete task:
```

Report to the user with the main result first, then a short table:

| Phase | Check Gate Yes/No | Evidence summary | Next step |
|---|---|---|---|
| Pn | No | Actual evidence or precise missing item | Specific remediation |

Do not say "finished" if only front-end demo data exists. Do not keep asking for confirmation for routine reversible steps. Pause only dependent work when an approval or external access is genuinely missing; complete independent authorized preparation first.

## L. UI implementation coverage

Use a restrained professional workspace UI: readable Thai labels, neutral surfaces, blue primary actions, distinct statuses with text, sidebar on desktop and responsive navigation on mobile. Essential forms need labels, inline errors, loading/disabled controls, focus management and confirmation for revoke/unbind/cancel actions.

Required screens: Auth/Signup/Reset; Dashboard; Create wizard (4 steps); Jobs/status tabs; Job detail/real preview/approval; Schedule week/list/item editor; Devices/detail/register/rename/unbind; Templates/editor; Environments/limits; Token create/copy/revoke; Agent list/session management; Billing/plans/checkout/pending/history; Settings; Notifications; Support; Admin Users/Plans/Jobs/Payments; Windows Agent configuration/device/job/activity/needs-action surfaces.

Live-data implementation must replace all UI demo numbers and fake success handlers. Optional reference: the earlier ClipFlow UI prototype may be supplied separately; its availability must not block implementing the routes and acceptance criteria here.

## M. Configuration and security boundaries

Create `.env.example` with empty/placeholding values, explicit comments and safe defaults. Suggested keys:

```dotenv
APP_ENV=development
DATABASE_URL=
REDIS_URL=
OBJECT_STORAGE_ENDPOINT=
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_ACCESS_KEY=
OBJECT_STORAGE_SECRET_KEY=
WEB_ORIGIN=http://localhost:5173
AI_PROVIDER=
AI_API_KEY=
BILLING_PROVIDER=sandbox
BILLING_API_KEY=
BILLING_WEBHOOK_SECRET=
POSTING_MODE=dry_run
```

Agent configuration is separate: `SERVER_URL`, `AGENT_USERNAME`, secret Token stored via customer credential storage, installation identity generated once. Environment scope comes from Server, not editable client claims. Do not copy Server DB/storage/billing credentials into the Agent.

Rendering workers run with resource/network restrictions appropriate to untrusted media. Validate source and any third-party download redirect or adapter-returned media address to prevent SSRF; an approved initial URL is not enough if the downloaded asset points elsewhere.

## N. Definition of product completion

The requested product is complete only when the applicable P0–P8 gates have evidence and sign-off, all P0 functional requirements are implemented, the Agent/Android matrix is validated, billing/quotas are correct, runbooks/restore are exercised, and the release is actually authorized. A deployable codebase may be prepared before release approval, but must be reported as ready for review rather than launched.

The plan is approximately 12 weeks under the team assumption in the original PRD. Development phases are deliverable milestones, not a guarantee that an AI agent can finish all external tests or commercial approvals within one session.

## O. Full product PRD, planning, gate checklist and UAT

The original product requirements follow. They preserve the complete business scope and 47 mandatory check IDs. The original version label identifies the baseline; this developer edition is version 1.1 above.

---

# ClipFlow — Product Requirements Document
## PRD, Delivery Plan และ Phase Check Gate (Yes / No)

Version 1.0 • 6 ตุลาคม 2569 • เจ้าของผลิตภัณฑ์: คุณปิยศักดิ์ / ผู้ได้รับมอบหมาย

สถานะ: Draft สำหรับเริ่มพัฒนา • ระยะเวลา: แผนตั้งต้น 12 สัปดาห์หลังเริ่มโครงการ • เขตเวลาเริ่มต้น: Asia/Bangkok

เอกสารนี้กำหนดสิ่งที่จะสร้างและหลักฐานที่ต้องตรวจ ยังไม่ได้ยืนยันว่าระบบจริงผ่านเกณฑ์ใดแล้ว ตัวเลขด้านสมรรถนะ โควตา และราคาเป็นข้อเสนอสำหรับทดสอบและอนุมัติใน Phase 0–1 ไม่ใช่ผลการทดสอบจริง

## 1. Executive brief

ClipFlow เป็นบริการสมาชิกแบบรายเดือน รับลิงก์ YouTube/Bilibili ที่ผู้ใช้มีสิทธิ์นำมาใช้ ผลิตคลิปแนวตั้งหลายคลิปจากหนึ่งต้นฉบับ สร้าง Title, Ending, Caption และ Hashtag แล้วตั้งโพสต์ทุก X ชั่วโมงไปยังโทรศัพท์ Android ที่ลงทะเบียน Serial ผ่าน Device Agent บนคอมพิวเตอร์ลูกค้า

การเชื่อม Agent ใช้ Username + Token ที่สร้างและคัดลอกจากเว็บ Token ผูกกับ Environment ฝั่ง Server และกำหนดจำนวน Agent ที่ลงทะเบียนกับจำนวน Session พร้อมกันแยกกัน โทรศัพท์หนึ่งเครื่องรับงานโพสต์ได้ครั้งละหนึ่งงาน

จุดที่ต้องพิสูจน์ก่อนลงทุนพัฒนาเต็มรูปแบบคือ การอ่านต้นฉบับที่อนุญาต การผลิตคลิปที่ใช้งานได้ และการโพสต์ผ่าน Android ที่ตรวจผลสำเร็จได้จริง หากเส้นทางโพสต์อัตโนมัติไม่ผ่านข้อกำหนดที่เกี่ยวข้องหรือไม่เสถียร ต้องตัดสินใจเรื่องรูปแบบบริการใหม่ก่อนผ่าน Gate 1 ไม่ใช้การเปลี่ยนช่องทางเพื่อหลีกเลี่ยงข้อจำกัด

### เป้าหมายและตัวชี้วัด

| เป้าหมาย | ตัวชี้วัดเสนอสำหรับ Pilot | วิธีวัด |
|---|---|---|
| ผู้ใช้เริ่มใช้งานได้ | อย่างน้อย 80% ของผู้ทดสอบลงทะเบียน Agent และเครื่องแรกสำเร็จภายใน 20 นาที | ทดสอบอย่างน้อย 10 ผู้ใช้ใหม่ บันทึกเวลาและจุดติดขัด |
| ผลิตคลิปได้ครบ | อย่างน้อย 95% ของ 50 งานต้นฉบับที่เข้าถึงได้และอยู่ในขอบเขตทดสอบผลิตสำเร็จ | บันทึกผลทุกงาน แยกข้อผิดพลาดจากสิทธิ์เข้าถึงต้นฉบับ |
| เผยแพร่ได้และยืนยันผลได้ | อย่างน้อย 95% ของ 50 งานที่มีเครื่องพร้อมและบัญชีถูกต้องยืนยันสำเร็จ | รายงานความสำเร็จ ความล้มเหลว และสถานะไม่ชัดเจนแยกกัน |
| ป้องกันความเสียหายสำคัญ | ไม่พบโพสต์ซ้ำ โพสต์ผิดบัญชี หรือข้อมูลลูกค้าข้าม Workspace ในชุด UAT | ทดสอบสถานการณ์เสี่ยงโดยเฉพาะ พร้อมหลักฐาน |
| มีต้นทุนที่รองรับรายเดือน | ทราบต้นทุนจริงต่อคลิปและต่อหนึ่งนาทีต้นฉบับ พร้อมกำไรขั้นต้นตามเป้าหมายที่ PO อนุมัติ | วัดต้นทุน Compute, AI, Storage, Transfer, Payment และ Support |

ยอดวิวและผู้ติดตามเป็นข้อมูลเพื่อพัฒนาคอนเทนต์ ไม่ใช่การรับประกันบริการ และยังไม่เป็นเงื่อนไขผ่าน MVP

## 2. Users, roles และขอบเขต

| Role | สิทธิ์หลัก |
|---|---|
| Workspace Owner | จัดการสมาชิก Token Environment เครื่อง งาน และตารางของตน |
| Platform Admin | จัดการแพ็กเกจ สถานะสมาชิก การชำระเงินและปัญหางาน โดยบันทึกการเข้าถึง |
| Device Agent | รับเฉพาะงานของ Workspace/Environment/เครื่องที่ได้รับอนุญาต ไม่มีสิทธิ์อ่าน Workspace อื่น |
| QA / Support | อ่านข้อมูลที่จำเป็นตามสิทธิ์ที่มอบหมาย ไม่เห็น Token เต็มหรือข้อมูลอ่อนไหวที่ไม่จำเป็น |

### MVP ต้องมี

- เว็บสมัครสมาชิก เข้าสู่ระบบ กู้รหัสผ่าน Dashboard และหน้าตั้งค่า
- รับลิงก์หนึ่งต้นฉบับต่อหนึ่งงาน รองรับ YouTube และ Bilibili ตามชนิดลิงก์ที่ผ่านการทดสอบ
- ตัดคลิป 9:16 หลายคลิป เลือกช่วงแบบ AI หรือสุ่มจากช่วงที่ผ่านการคัดแล้ว
- Title, Ending, Subtitle, Caption, Hashtag ที่แก้ไขได้ พร้อม Template
- ตัวอย่างวิดีโอจริงก่อนเผยแพร่ โหมดตรวจคลิปก่อนและโหมดอัตโนมัติที่ผู้ใช้เปิดใช้เอง
- ตารางโพสต์ทุก X ชั่วโมง ช่วงเวลาอนุญาต เขตเวลา เครื่องปลายทาง และนโยบายเมื่อเครื่อง Offline
- Environment, Generate/Copy/Revoke Token, Agent registration, Session และ Serial registration
- Agent บน Windows เป็นขอบเขตเริ่มต้น Android รุ่นที่ผ่าน Compatibility matrix และหนึ่ง Session ทำงานต่อการติดตั้ง
- สมาชิกแบบรายเดือน โควตา และประวัติการชำระเงิน ผ่านหนึ่งช่องทางชำระที่เลือกใน Phase 0
- Admin, Audit log, Monitoring, Backup และการกู้คืนงาน

### หลัง MVP

- Team roles, Agency workspace หลายทีม, Voiceover แบบพรีเมียม, Analytics ดึงจากแพลตฟอร์ม, Credit top-up และหลายช่องทางชำระเงิน
- Agent สำหรับ macOS/Linux การครอปติดตามบุคคลขั้นสูง และการนำเข้าหลายลิงก์พร้อมกัน

### ไม่รวมในขอบเขต

- การสร้างบัญชี TikTok อัตโนมัติ การข้าม CAPTCHA การหลีกเลี่ยงการจำกัดบัญชีหรือการตรวจเนื้อหา
- ดาวน์โหลดแหล่งที่ต้องข้ามระบบป้องกัน เข้าถึงบัญชีคนอื่น หรือใช้วิดีโอที่ไม่มีสิทธิ์
- การรับประกันว่าทุกลิงก์ดาวน์โหลดได้ ทุกโทรศัพท์รองรับ หรือ TikTok จะเผยแพร่ตรงนาทีที่กำหนด
- การนำ TikTok Direct Post API มาแทนโดยอัตโนมัติ ต้องตรวจ Intended use และข้อกำหนดก่อนเลือก

## 3. Product journeys และ UI coverage

| Journey | หน้าจอ | ผลลัพธ์ที่ผู้ใช้ต้องเข้าใจ |
|---|---|---|
| เริ่มสมาชิก | Sign up → Billing → Dashboard | แพ็กเกจ วันหมดอายุ และโควตา |
| เชื่อมเครื่อง | Connection → Generate Token → Agent → Devices | เครื่องพร้อม/ไม่พร้อมและเหตุผล |
| ผลิตคลิป | Create: ต้นฉบับ → รูปแบบ → เครื่อง/เวลา → ตรวจและสร้าง | จำนวนคลิป ค่าใช้โควตา และสถานะงาน |
| ตรวจคลิป | Jobs → Job detail → Approve | Preview จริง ข้อความ และช่วงต้นฉบับ |
| เผยแพร่ | Schedule → Agent → Post result | เวลานัด ผลจริง และเหตุผลเมื่อเลื่อน |
| จัดการปัญหา | Notifications → Devices / Job detail / Support | วิธีแก้และงานที่ถูกพัก |
| ดูแลบริการ | Admin: Users / Plans / Jobs / Payments | หลักฐานการเปลี่ยนแปลงและผลต่อสมาชิก |

ทุกหน้าต้องมีสถานะ Loading, Empty, Validation error, Permission denied และ Success ตามบริบท หน้าตารางต้องรองรับมือถือ และไม่แสดง Credential เต็มในรายการหรือ Log

UI ต้นแบบที่ออกแบบแล้วเป็นเอกสารอ้างอิงด้านโครงสร้างและ Interaction เท่านั้น ราคาตัวอย่าง ข้อมูลตัวอย่าง และปุ่มจำลองไม่ถือเป็นฟังก์ชันที่พัฒนาเสร็จแล้ว

## 4. Functional requirements และ Acceptance criteria

Priority: P0 = จำเป็นก่อนเปิดบริการ; P1 = ทำหลัง MVP ได้

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-01 | P0 | สมาชิกและ Workspace | ผู้ใช้เข้าสู่ระบบได้และเข้าถึงได้เฉพาะ Workspace ที่มีสิทธิ์; กู้รหัสผ่านไม่เปิดเผยว่าบัญชีมีอยู่หรือไม่ |
| FR-02 | P0 | รับลิงก์และสิทธิ์ต้นฉบับ | ตรวจ URL/ชนิดแหล่ง จำกัดความยาวและขนาด เก็บคำยืนยันสิทธิ์และแหล่งที่มา; ปฏิเสธ URL ที่ไม่รองรับ |
| FR-03 | P0 | ดาวน์โหลดและ Metadata | แยกสถานะต้นฉบับไม่พบ/เข้าถึงไม่ได้/ตัวดาวน์โหลดผิดพลาด; ไม่ Retry ไม่จำกัด |
| FR-04 | P0 | คัดช่วงและ Random | ช่วงที่ใช้มี Start/End; ไม่สุ่มตัดกลางประโยคโดยไม่มีการตรวจ; เก็บ Seed และ Template version สำหรับทำซ้ำ |
| FR-05 | P0 | จำนวนคลิป | ประเมินจำนวนที่สร้างได้จริง ถ้าเนื้อหาไม่พอให้ลดจำนวนพร้อมแจ้งผู้ใช้ก่อนใช้โควตาเพิ่ม |
| FR-06 | P0 | Render | ได้ไฟล์ MP4 9:16 พร้อมเสียงตามการตั้งค่า; ตรวจไฟล์ด้วย Media probe และเล่นได้บนเครื่องทดสอบ |
| FR-07 | P0 | ข้อความและซับ | สร้าง Title/Ending/Caption/Hashtag จากเนื้อหาที่เลือก แก้ไขและเก็บเวอร์ชันได้; ภาษาไทยไม่เป็นตัวอักษรเสีย |
| FR-08 | P0 | Review/Auto mode | Review mode ต้องอนุมัติคลิปก่อนคิวโพสต์; Auto mode ต้องเปิดใช้ชัดเจนและผ่านการตรวจระบบก่อนทุกคลิป |
| FR-09 | P0 | Schedule ทุก X ชั่วโมง | รับจำนวนเต็ม X ≥ 1 ชั่วโมง; ตัวเลือกเริ่มต้น 1/2/3/6/12/24; คำนวณจากเวลานัดล่าสุด ไม่ใช่เวลาโพสต์จริง |
| FR-10 | P0 | Window/Timezone | เก็บเวลาอ้างอิง UTC และ IANA timezone; ช่วงโพสต์เป็น [เวลาเริ่ม, เวลาสิ้นสุด); MVP ไม่รองรับช่วงข้ามเที่ยงคืน |
| FR-11 | P0 | Offline/Collision | เลือกข้ามรอบหรือเลื่อน; ไม่มีการส่งงานค้างทั้งหมดติดกัน; เวลาเครื่องเดียวกันชนต้องแก้หรือแจ้งก่อนเริ่ม |
| FR-12 | P0 | Token | Username เป็นตัวระบุบัญชี Token เป็นหลักฐานสิทธิ์; Generate/Copy ครั้งแรก, Expiry, Revoke, Rotate; ไม่เก็บ Token เต็มบน Server |
| FR-13 | P0 | Environment quota | แยก registered_agent_limit และ concurrent_session_limit; ผูก Environment กับ Token ฝั่ง Server; มีข้อจำกัดตามแพ็กเกจ |
| FR-14 | P0 | Agent identity | installation_id คงเดิมเมื่อ Restart; Reconnect ไม่กินทะเบียนเพิ่ม; Duplicate Session ต้องไม่รับงานพร้อมกัน |
| FR-15 | P0 | Serial registration | ค้น Serial ผ่าน Agent แสดงสถานะ unauthorized/offline; Serial ไม่ใช่ Credential; ป้องกันการผูกเครื่องซ้ำที่มีเจ้าของอยู่ |
| FR-16 | P0 | บัญชี TikTok | เก็บ expected_account; หากตรวจบัญชีจริงไม่ตรงหรืออ่านไม่ได้ต้องพัก ห้ามเดาสุ่ม |
| FR-17 | P0 | Device posting | ดาวน์โหลดไฟล์ ตรวจ Hash ส่งเข้าเครื่อง ตรวจ Gallery กรอกข้อความไทย และดำเนินการตามสถานะ UI |
| FR-18 | P0 | Verify/Retry | บันทึก Attempt; ผลไม่ชัดเจนเป็น UNKNOWN; ไม่ Retry หลังส่งโดยไม่มีการตรวจ; สำเร็จเมื่อมีหลักฐานผลโพสต์ |
| FR-19 | P0 | Pause/Cancel | หยุดงานที่ยังไม่เริ่มได้; หลังเริ่มส่งต้องแสดงว่าอาจยกเลิกไม่ทันและติดตามผลต่อ |
| FR-20 | P0 | Monthly billing | สมัคร/ต่ออายุ/หมดอายุจากสถานะธุรกรรมฝั่ง Server; ไม่ให้สิทธิ์จากหน้า Redirect ของ Client อย่างเดียว |
| FR-21 | P0 | Quota ledger | กันโควตาแบบ Atomic เมื่อเริ่มงาน ใช้จริงเมื่อผลิตสำเร็จ คืนรายการที่เข้าเงื่อนไข; หนึ่งเหตุการณ์ลง Ledger ได้ครั้งเดียว |
| FR-22 | P0 | Admin/Audit | เปลี่ยนแพ็กเกจ/สถานะ/โควตาพร้อมเหตุผล ผู้กระทำ เวลา และค่าก่อน/หลัง; จำกัดสิทธิ์การเข้าถึง |
| FR-23 | P0 | Alert/Support | แจ้งงานผิดพลาด เครื่อง Offline ผลไม่ชัดเจน และสมาชิกหมดอายุ; Support อ้างอิง Job ID ได้ |
| FR-24 | P1 | Team/Premium | เพิ่มสมาชิกทีม เสียงพากย์ เครดิตเพิ่ม และ Analytics หลัง MVP โดยไม่เปลี่ยนกติกางานเดิม |

## 5. กติกาตารางโพสต์

หนึ่งต้นฉบับสร้าง N คลิปที่ต่างกันและผูกกับ Schedule series เดียว เวลาของคลิปแรกมาจาก Start time คลิปถัดไปมาจากเวลานัดก่อนหน้า + X ชั่วโมง ถ้าอยู่นอกช่วงอนุญาตให้เลื่อนไปเวลาเริ่มของช่วงถัดไป เมื่อครบ N คลิปให้จบ Series ไม่วนโพสต์ซ้ำเอง

ตัวอย่าง: เริ่ม 7 ต.ค. 2569 09:00; N=6; X=2; Window 09:00–21:00; Asia/Bangkok → 09:00, 11:00, 13:00, 15:00, 17:00, 19:00

ตัวอย่างข้ามวัน: เริ่ม 7 ต.ค. 19:00; N=3; X=2; Window 09:00–21:00 → 7 ต.ค. 19:00, 8 ต.ค. 09:00, 8 ต.ค. 11:00 เพราะ 21:00 อยู่นอก Window

| เหตุการณ์ | พฤติกรรม |
|---|---|
| Clip ยังไม่ Ready/Approved เมื่อถึงเวลา | ไม่โพสต์; แสดงเหตุผล และใช้กติกาเลื่อน/ข้ามที่ตั้งไว้ |
| เครื่อง Offline | ไม่สะสม Burst; เลื่อนคลิปและรายการต่อท้ายโดยรักษาช่วงห่าง หรือข้ามตามตัวเลือก |
| Queue เครื่องเดียวชนกัน | ตรวจตอนสร้างและก่อน Claim; แสดงเวลาทางเลือก ไม่ส่งพร้อมกัน |
| Pause แล้ว Resume | ไม่ทำ Catch-up ทันที; คำนวณตารางที่เหลือใหม่ และให้เห็น Preview |
| สมาชิกหมดอายุ | พักงานใหม่และงานโพสต์ที่ยังไม่เริ่ม; ให้ผู้ใช้เห็นงานคงค้างและเงื่อนไขกลับมาใช้ |
| เปลี่ยนเครื่อง/เวลา | เปลี่ยนได้เฉพาะงานที่ยังไม่ Claim; งานกำลังทำต้องไม่ถูกอีก Agent รับซ้ำ |
| ยกเลิกหลังเริ่มอัปโหลด | อาจยกเลิกไม่ทัน; แสดงสถานะติดตามผล ห้ามแสดง Cancelled หากอาจโพสต์แล้ว |
| เวลาประมวลผลแพลตฟอร์ม | แยก scheduled_at, started_at, submitted_at และ verified_at |

## 6. Agent, Environment และ Session

ใช้การเชื่อมออกจาก Agent ผ่าน HTTPS ไม่เปิด ADB สู่อินเทอร์เน็ต Token เป็นสิทธิ์ของบัญชีและ Environment; Serial ระบุเครื่องที่เชื่อมกับ Agent; installation_id เป็นรหัสประจำการติดตั้ง ไม่ใช่หลักฐานว่าเป็นคอมพิวเตอร์จริงที่ปลอมไม่ได้

ค่าเสนอเริ่มต้น: Heartbeat ทุก 15 วินาที Session stale เมื่อขาด Heartbeat 60 วินาที และ Session หมดอายุภายใน 90 วินาที ต้องปรับตามผลทดสอบเครือข่ายจริง

| กรณี | Expected result |
|---|---|
| Token ถูกต้อง Username ตรงเจ้าของ | ออก Session ที่มี Scope ตาม Environment |
| Username ไม่ตรง Token | ปฏิเสธ ไม่เปิดเผยข้อมูลเจ้าของ Token |
| Reconnect ของ installation_id เดิม | ใช้ทะเบียนเดิม ไม่เพิ่มจำนวน Agent |
| การติดตั้งใหม่ | นับทะเบียนใหม่และตรวจ registered_agent_limit |
| Agent process ซ้ำ | ใช้ Local process lock และ Server session fencing; หนึ่ง Session รับงานได้ |
| Session เต็ม | ปฏิเสธและแสดง Session/Agent ที่ผู้ใช้จัดการได้ |
| ปลอมชื่อ Environment จาก Client | Server ใช้ Environment ของ Token ไม่ใช้ชื่อที่ Client ส่งมาทับ |
| Token หมดอายุ/ถูก Revoke | หยุดรับงานใหม่และต่อ Session; ตรวจผลของ Attempt ที่เริ่มแล้วต่ออย่างปลอดภัย |
| Serial เปลี่ยน หรืออุปกรณ์ใหม่ | ไม่ผูกอัตโนมัติ ให้ลงทะเบียนใหม่พร้อมตรวจสิทธิ์ |

ผู้ใช้ต้องดูและยกเลิกทะเบียน Agent เก่าได้ การ Uninstall โดยไม่มีการคืนทะเบียนไม่ควรทำให้โควตาเสียถาวร เมื่อ Token ถูก Revoke ให้เพิกถอน Session ที่เกี่ยวข้องภายใน 60 วินาทีเป็นเกณฑ์เสนอ

## 7. Architecture, data และ API boundaries

องค์ประกอบ: Web UI → Application API → Database/Quota ledger → Render queue/Worker → Object storage → Scheduler → Environment/Device queue → Customer Agent → Android → Result verification

Stack ตั้งต้นสำหรับประเมิน: Web React/TypeScript, API Python/FastAPI, Database PostgreSQL, Queue Redis, Render FFmpeg, Source adapter yt-dlp, Android automation ADB/UIAutomator2 ไม่ผูกกับหมายเลขเวอร์ชันใน PRD ให้ล็อกเวอร์ชันหลัง Compatibility test

| Entity | ข้อมูลสำคัญ |
|---|---|
| Workspace/User | owner, roles, timezone, status |
| Plan/Subscription/Payment | version, limits, period, payment event, status |
| QuotaLedger | reservation, usage, refund, reference, idempotency_key |
| Environment/AgentToken | workspace, limits, token_hash, scope, expiry, revoked_at |
| AgentInstallation/Session | installation_id, environment, heartbeat, lease, fencing generation |
| Device | workspace, environment, agent, adb_serial, expected_account, readiness |
| Source/Job | URL, source_id, rights declaration, metadata, status, cost |
| Clip/RenderVersion | start/end, random seed, template version, media hash, approval |
| ScheduleSeries/ScheduleItem | interval, window, timezone, device, policy, scheduled_at |
| PublishAttempt | attempt_id, lease generation, state, submitted_at, evidence, verified_at |
| AuditEvent | actor, action, target, timestamp, before/after ที่ไม่รวม Credential |

API groups: Auth/Workspace; Jobs/Clips; Templates; Schedules; Environments/Tokens; Agent authenticate/heartbeat/claim/result; Devices; Billing webhook; Admin. ทุก Resource ตรวจ Workspace ownership บน Server และทุก Endpoint ที่เปลี่ยนสถานะสำคัญต้องรองรับการส่งซ้ำอย่างปลอดภัย

Job flow: RECEIVED → SOURCE_VALIDATED → DOWNLOADING → ANALYZING → RENDERING → READY_FOR_REVIEW → APPROVED → SCHEDULED. เส้นทางผิดพลาด: NEEDS_ACTION / FAILED / CANCELLED

Publish flow: SCHEDULED → CLAIMED → TRANSFERRING → PREPARING → SUBMITTING → VERIFYING → VERIFIED_SUCCESS. เส้นทางอื่น: RETRYABLE_FAILED / UNKNOWN / NEEDS_ACTION / SKIPPED / CANCELLED

หลัง SUBMITTING ถ้า Agent หาย ห้ามปล่อย Lease แล้วสั่งอีก Agent โพสต์ซ้ำทันที ต้องเข้าสู่ UNKNOWN และตรวจผล เพราะการกด UI และการเขียนสถานะ Server ไม่เป็นธุรกรรมเดียวกัน ระบบจึงรับประกัน Exactly-once posting ผ่าน UI ไม่ได้ ต้องใช้การป้องกันและตรวจสอบแทน

## 8. Billing และ unit economics

โมเดล: สมาชิกต่อเดือน + โควตาคลิป + นาทีต้นฉบับ + จำนวนเครื่อง + จำนวน Agent/Session ตามแพ็กเกจ เลือกช่องทางชำระเงินแรกหลังตรวจการใช้งานธุรกิจจริง การเรียกเก็บรายเดือนและ Auto-renew เป็นคนละความสามารถ Auto-renew เปิดเมื่อผู้ให้บริการและวิธีชำระรองรับเท่านั้น

ราคาที่เห็นใน UI เดิม ฿490 / ฿990 / ฿2,990 เป็นตัวอย่าง ต้องยืนยันใหม่จากต้นทุนและกลุ่มลูกค้าใน Gate 6 ก่อนเปิดขาย

| กรณี | กติกาที่ต้องกำหนดและทดสอบ |
|---|---|
| เริ่ม Render | กันคลิปและนาทีต้นฉบับแบบ Atomic; ไม่ให้สองงานใช้ยอดเดียวกัน |
| Render สำเร็จ | เปลี่ยน Reservation เป็น Usage ครั้งเดียว |
| Source/Render ล้มเหลวจากระบบ | คืนส่วนที่ไม่ได้ใช้ตามนโยบาย; ไม่คืนซ้ำเมื่อ Event ซ้ำ |
| Render สำเร็จแต่เครื่อง Offline | ไม่ Render/คิดโควตาซ้ำเมื่อ Retry การโพสต์ |
| เปลี่ยนข้อความ | ไม่คิดโควตา Render ถ้าไม่สร้างไฟล์ใหม่; การ Render ใหม่แสดงยอดก่อนเริ่ม |
| Webhook ชำระเงินซ้ำ/ล่าช้า | ตรวจลายเซ็นและ Provider event ID; สิทธิ์ไม่ถูกเพิ่มซ้ำหรือย้อนสถานะผิด |
| หมดอายุ/ต่ออายุ | ขอบเขตรอบสมาชิกและโควตาชัดเจน ไม่มีการ Reset สองครั้ง |
| เปลี่ยนแพ็กเกจ | MVP ใช้รอบถัดไปเป็นค่าเริ่มต้น; การ Upgrade ทันที/Proration ต้องมีนโยบายก่อนเปิด |
| Refund/Dispute | Admin มีสถานะและประวัติสิทธิ์ที่เปลี่ยน; ไม่ลบ Payment history |

ต้นทุนต่อคลิป = Download/Analysis + AI/Text + Render + Storage/Transfer + Payment allocation + Support allocation. ตรวจทั้ง Average และ P95 ของงานยาว แยกต้นทุนงานที่สำเร็จกับ Retry เพื่อกำหนดราคาที่รองรับการใช้งานจริง

## 9. Non-functional requirements

| ID | Requirement | เกณฑ์เสนอ / หลักฐาน |
|---|---|---|
| NF-01 | Tenant isolation | Cross-tenant tests ผ่านทุก Resource และ Download link; ไม่รั่วข้าม Workspace |
| NF-02 | Credential protection | Token entropy สูง เก็บ Hash ฝั่ง Server เก็บ Agent secret ใน Credential store ที่เหมาะสม; ไม่พบ Token ใน Log/URL |
| NF-03 | URL/file safety | Allowlist แหล่งต้นฉบับ ตรวจ Redirect/DNS/Private address ป้องกัน SSRF; จำกัดขนาด/ระยะเวลา Render worker มี Resource limit |
| NF-04 | API responsiveness | P95 < 1 วินาทีสำหรับ CRUD ทั่วไปที่ 50 concurrent users ในชุด Load test; ไม่รวม Render/Download |
| NF-05 | Scheduler dispatch | 95% ของงานพร้อมใน Load test เริ่ม Claim ภายใน 60 วินาทีจากนัด; ไม่รวมการเผยแพร่ภายนอก |
| NF-06 | Storage/retention | อายุไฟล์ตามแพ็กเกจ ตัวเสนอ 30 วัน; Lifecycle ลบจริงและไม่ลบไฟล์งานกำลังทำ |
| NF-07 | Recovery | Backup พร้อม Restore ที่ทดสอบได้; เป้าหมาย RPO ≤ 24 ชั่วโมง RTO ≤ 4 ชั่วโมงสำหรับ Pilot |
| NF-08 | Observability | Job/Clip/Attempt ID เชื่อม Log และ Metrics; Alert queue lag, render failure, unknown post, stale agent |
| NF-09 | Accessibility/responsive | ใช้คีย์บอร์ดได้ ภาษาไทยอ่านได้ที่ 360px/desktop และซูม 200%; Focus และ Error ชัดเจน |
| NF-10 | Agent update | แพ็กเกจตรวจแหล่งที่มา/ความสมบูรณ์ได้ เวอร์ชันรองรับชัดเจน ไม่ Update ระหว่าง Submit; Rollback ได้ |

## 10. Delivery planning — 9 phases / 12 สัปดาห์

สมมติฐานทีม: PO/PM 1 คน, Full-stack 1 คน, Backend/Video/Agent 1 คน, QA/DevOps 1 คน โดยบางบทบาทอาจเป็น Part-time แผนนี้เป็นประมาณการ ไม่ใช่กำหนดส่งที่ผูกพัน ถ้าทีมเล็กลงหรือ POC ไม่ผ่านให้ประมาณการใหม่

| Phase | ช่วงเวลา | งานและ Deliverable | Owner | Dependency |
|---|---|---|---|---|
| P0 — Scope & design baseline | W1 | PRD, UI map, MVP backlog, ราคาสมมติ, risk/decision register, rights/service policy | PO + Tech Lead | ไม่มี |
| P1 — Feasibility proof | W1–W2 | ทดสอบต้นฉบับทั้งสองแพลตฟอร์ม Render/ซับไทย ADB posting/verify Compatibility และต้นทุน | Video/Agent + QA | Scope P0; Gate 0 ก่อนตัดสินใจลงทุนเต็ม |
| P2 — SaaS foundation | W3–W4 | Auth, tenant, schema, Environment/Token/Session, device registry, CI/CD | Full-stack + Backend | Gate 1 Yes |
| P3 — Video production | W5–W6 | Ingest, analysis, random, render, metadata, review, quota reservation integration | Video/Backend + QA | Gate 2 Yes |
| P4 — Scheduler | W7 | Series/items, interval/window/timezone, collision, pause/offline, preview | Backend + Full-stack | Gate 3 Yes |
| P5 — Agent & publishing | W8–W9 | Agent installer, queue claim, device lock, transfer, posting, verify, recovery | Agent + QA | Gate 4 Yes |
| P6 — Billing & administration | W10 | Payment sandbox/live readiness, subscription, ledger, Admin/Audit, retention | Backend + Full-stack | Gate 5 Yes; prototype billing ทำเตรียมได้ก่อน |
| P7 — Pilot/UAT | W11 | ทดสอบครบ Journey, 10 ผู้ใช้, fault/load/security test, cost/reliability report | QA + PO + Ops | Gate 6 Yes |
| P8 — Launch readiness | W12 | Restore drill, deployment, rollback, support runbook, staged release | Ops + PO | Gate 7 Yes |

เส้นทางวิกฤต: POC ความเป็นไปได้ → Tenant/Agent identity → Video → Scheduler → Posting verification → Billing → UAT → Launch. งานเตรียมเอกสารและ Prototype ทำล่วงหน้าได้ แต่ห้ามเริ่ม Phase production ที่อาศัย Gate ที่ยัง No โดยไม่มีการทบทวนแผน

### Planning cadence

- Weekly plan: PO/PM ตรวจงานเสร็จ งานค้าง ความเสี่ยง และหลักฐานที่ต้องใช้ใน Gate ถัดไป
- Demo: แสดง End-to-end slice ทุกสัปดาห์ ไม่ถือ Screenshot หรือ UI จำลองเป็นการผ่าน Backend Gate
- Gate review: ผู้ตรวจ QA/Tech Lead เสนอผล PO ตัดสินใจ Yes/No พร้อมวันที่และ Evidence link
- การเปลี่ยน Scope: บันทึกเหตุผล ผลต่อต้นทุน/เวลา/Acceptance criteria และ PRD version ใหม่

## 11. Check Gate — กติกา Yes / No

ทุกข้อด้านล่างเป็นข้อบังคับของ Gate นั้น ให้เลือก Yes เฉพาะเมื่อมีหลักฐานตรงตามเกณฑ์; No เมื่อไม่ผ่านหรือยังไม่มีหลักฐาน ต้องเขียนเหตุผลแยกเป็น “ทดสอบไม่ผ่าน” หรือ “ยังไม่ได้ทดสอบ” ห้ามใช้คะแนนเฉลี่ยชดเชยข้อบังคับที่ No

Phase ผ่านเมื่อทุกข้อบังคับเป็น Yes และมีผู้อนุมัติลงชื่อ ข้อสรุป Phase ใช้ Yes/No เท่านั้น ส่วน “ยังไม่ได้ประเมิน” เป็นสถานะการทำงาน ไม่ใช่การอนุมัติผ่าน ณ วันที่เอกสารนี้สร้างยังไม่มี Gate ใดผ่าน

สำหรับ Gate ที่ No: ระบุ Action owner, due date, หลักฐานที่ขาด แล้วตรวจซ้ำเฉพาะข้อที่แก้และ Regression ที่ได้รับผลกระทบ ผู้อนุมัติไม่จำเป็นต้องเป็นเจ้าของทุกงานพัฒนา แต่ต้องเห็นหลักฐานก่อนตัดสินใจ

### Gate 0 — Scope & UI baseline

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G0-01 | PO ยืนยัน MVP, สิ่งที่เลื่อน และเกณฑ์ยอมรับแล้วหรือไม่? | PRD version ที่อนุมัติ | ☐ Yes ☐ No |
| G0-02 | UI ครบ Journey รวมข้อผิดพลาดและข้อมูลที่ยังต้องใช้จริงหรือไม่? | Screen map + walkthrough | ☐ Yes ☐ No |
| G0-03 | นิยาม Environment, ทะเบียน Agent, Session, Serial และบัญชีปลายทางชัดเจนหรือไม่? | Identity/permission model | ☐ Yes ☐ No |
| G0-04 | กติกา Schedule, Offline, Collision และ UNKNOWN ได้ข้อสรุปหรือไม่? | Decision register | ☐ Yes ☐ No |
| G0-05 | มีผู้รับผิดชอบ ทีม งบ POC และตัวอย่างต้นฉบับที่มีสิทธิ์หรือไม่? | Resource plan + test corpus | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: PO • หาก No: แก้ Scope/Decision ก่อนเริ่มสร้างฐานระบบเต็ม

### Gate 1 — Feasibility proof

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G1-01 | ต้นฉบับที่อนุญาตอย่างน้อย 5 ลิงก์ต่อแพลตฟอร์มอ่านได้ หรือชนิดที่ไม่รองรับถูกจำกัดอย่างชัดเจนหรือไม่? | Source compatibility report | ☐ Yes ☐ No |
| G1-02 | สร้างอย่างน้อย 3 คลิปต่อชุดต้นฉบับทดลองและเล่นภาพ/เสียง/ซับไทยได้จริงหรือไม่? | MP4 samples + QA record | ☐ Yes ☐ No |
| G1-03 | โทรศัพท์อย่างน้อย 2 รุ่นที่เลือกสามารถส่งไฟล์ กรอกภาษาไทย และตรวจผลโพสต์ได้หรือไม่? | Device matrix + authorized posting evidence | ☐ Yes ☐ No |
| G1-04 | เมื่อผลโพสต์ไม่ชัดเจน POC พักงานและไม่โพสต์ซ้ำโดยอัตโนมัติหรือไม่? | Disconnect/recovery test | ☐ Yes ☐ No |
| G1-05 | มีการตรวจข้อกำหนดแหล่งต้นฉบับ/ช่องทางเผยแพร่ และตัดสินใจว่ารูปแบบบริการนี้เปิดใช้ได้หรือไม่? | Dated review + PO decision | ☐ Yes ☐ No |
| G1-06 | มีต้นทุนจริงและเวลาประมวลผลเบื้องต้น พร้อมข้อจำกัดที่ยอมรับได้หรือไม่? | Benchmark + cost sheet | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: PO + Tech Lead • หาก No: หยุดขยาย SaaS และแก้ความเป็นไปได้ หรือเปลี่ยน Scope แล้วอนุมัติใหม่

### Gate 2 — SaaS foundation

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G2-01 | สมัคร/เข้า/กู้รหัสผ่านและ Tenant isolation ผ่านหรือไม่? | Auth + cross-tenant tests | ☐ Yes ☐ No |
| G2-02 | Token สร้าง/คัดลอกครั้งแรก/หมดอายุ/Revoke ได้ และไม่ปรากฏใน Log หรือไม่? | Token lifecycle + log scan | ☐ Yes ☐ No |
| G2-03 | Reconnect, Session ซ้ำ, Environment ปลอม และจำนวนเต็มถูกจัดการถูกต้องหรือไม่? | Agent identity tests | ☐ Yes ☐ No |
| G2-04 | ลงทะเบียน Serial ที่พร้อมใช้ได้และไม่ผูกเครื่องของผู้อื่นได้หรือไม่? | Device ownership tests | ☐ Yes ☐ No |
| G2-05 | Migration, CI/CD และ Staging deploy/rollback ทำซ้ำได้หรือไม่? | Build/deploy report | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: Tech Lead + QA • หาก No: แก้สิทธิ์และฐานข้อมูลก่อนรับงานวิดีโอจริงหลายลูกค้า

### Gate 3 — Video production

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G3-01 | Ingest จำกัด URL/Redirect/ขนาด/ความยาวและป้องกันเข้าถึงเครือข่ายภายในได้หรือไม่? | URL/SSRF/resource tests | ☐ Yes ☐ No |
| G3-02 | การเลือกช่วง Random บันทึก Seed และ Render version พร้อมทำซ้ำได้หรือไม่? | Reproducibility tests | ☐ Yes ☐ No |
| G3-03 | ไฟล์ 9:16 เล่นได้ Title/Ending/ซับไม่ล้น และภาษาไทยถูกต้องหรือไม่? | Media probe + visual/audio review | ☐ Yes ☐ No |
| G3-04 | เนื้อหาไม่พอ/Render ล้มเหลว/Cancel คืนหรือใช้โควตาถูกต้องครั้งเดียวหรือไม่? | Job + ledger tests | ☐ Yes ☐ No |
| G3-05 | Review mode ไม่ส่งคลิปที่ยังไม่อนุมัติ และ Auto mode ตรวจทุกคลิปหรือไม่? | Approval boundary tests | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: Video Lead + QA • หาก No: ไม่ส่งคลิปเข้าคิวเผยแพร่

### Gate 4 — Scheduler

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G4-01 | ทุก X ชั่วโมง วันถัดไป และขอบ Window ให้ผลตรงตัวอย่างที่อนุมัติหรือไม่? | Schedule calculation tests | ☐ Yes ☐ No |
| G4-02 | Offline/Pause/Resume ไม่ทำ Burst และไม่ใช้คลิปเดิมซ้ำหรือไม่? | Recovery schedule tests | ☐ Yes ☐ No |
| G4-03 | Collision และ Device lock ป้องกันสองงานเริ่มพร้อมกันหรือไม่? | Concurrent claim test | ☐ Yes ☐ No |
| G4-04 | แก้/ยกเลิกงานที่ยังไม่เริ่มได้และงาน Claim แล้วไม่ถูกส่งซ้ำหรือไม่? | Schedule mutation tests | ☐ Yes ☐ No |
| G4-05 | Dispatch เป้าหมาย 95% ภายใน 60 วินาทีผ่านใน Load test และ UI แยกเวลานัดกับผลจริงหรือไม่? | Load + UI status report | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: Backend Lead + QA • หาก No: ห้ามเปิดการโพสต์ตามตารางจริง

### Gate 5 — Agent & publishing

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G5-01 | Agent ติดตั้ง/อัปเดต/ย้อนเวอร์ชันได้บน Windows baseline และโทรศัพท์ใน Matrix หรือไม่? | Installer/update tests | ☐ Yes ☐ No |
| G5-02 | ตรวจ Hash โอนไฟล์ พบไฟล์ใน Gallery และใส่ Caption/Hashtag ไทยได้หรือไม่? | Transfer/UI tests | ☐ Yes ☐ No |
| G5-03 | ผิดบัญชี Login wall และ CAPTCHA ทำให้พักงานโดยไม่เดาหรือข้ามหรือไม่? | Needs-action tests | ☐ Yes ☐ No |
| G5-04 | Agent crash/เน็ตหลุดหลัง Submit เข้า UNKNOWN และไม่ Retry แบบเสี่ยงซ้ำหรือไม่? | Fault injection evidence | ☐ Yes ☐ No |
| G5-05 | เผยแพร่จริงในชุดทดสอบที่อนุญาตและตรวจผลตามหลักฐานได้ โดยไม่พบโพสต์ผิดบัญชีหรือซ้ำหรือไม่? | Authorized end-to-end tests | ☐ Yes ☐ No |
| G5-06 | Revoke/Session expiry/Lease generation ป้องกัน Agent เก่ารับงานใหม่หลังหมดสิทธิ์หรือไม่? | Fencing/revocation tests | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: Agent Lead + QA + PO • หาก No: ใช้ได้เฉพาะทดสอบส่วนที่ไม่เผยแพร่และแก้ผลตรวจให้ครบ

### Gate 6 — Billing & administration

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G6-01 | ราคา โควตา วันหมดอายุ Refund/Upgrade/Retention มีนโยบายอนุมัติหรือไม่? | Commercial policy + cost model | ☐ Yes ☐ No |
| G6-02 | ช่องทางชำระที่เลือกพร้อมใช้ และ Success/Fail/Pending ทดสอบได้หรือไม่? | Provider setup + sandbox results | ☐ Yes ☐ No |
| G6-03 | Webhook ปลอม/ซ้ำ/ผิดลำดับไม่เปิดสิทธิ์หรือคิดเงิน/โควตาซ้ำหรือไม่? | Payment idempotency tests | ☐ Yes ☐ No |
| G6-04 | หมดอายุ/ต่ออายุ/แพ็กเกจใหม่ทำให้คิวและโควตาถูกต้องหรือไม่? | Subscription boundary tests | ☐ Yes ☐ No |
| G6-05 | Admin/Audit/Retention และการเข้าถึงข้อมูลตามสิทธิ์ทำงานจริงหรือไม่? | Admin/retention/access tests | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: PO + Finance owner + QA • หาก No: ไม่เปิดรับสมาชิกแบบชำระเงินจริง

### Gate 7 — Pilot / UAT

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G7-01 | ผู้ใช้ใหม่อย่างน้อย 10 คนทดสอบ Journey และ ≥80% เริ่มใช้งานใน 20 นาทีได้หรือไม่? | Onboarding study | ☐ Yes ☐ No |
| G7-02 | อย่างน้อย 50 งานผลิตและ 50 งานโพสต์ที่เข้าเงื่อนไขผ่านเป้าหมาย ≥95% พร้อมรายงาน Unknown หรือไม่? | Pilot reliability report | ☐ Yes ☐ No |
| G7-03 | ไม่พบโพสต์ซ้ำ ผิดบัญชี Tenant leak หรือยอดเงิน/สิทธิ์ผิด และไม่มีบั๊ก Critical/High ค้างหรือไม่? | Defect register + regression | ☐ Yes ☐ No |
| G7-04 | Load, security, ภาษาไทย, mobile และ accessibility tests ตาม NF ผ่านหรือไม่? | Consolidated QA report | ☐ Yes ☐ No |
| G7-05 | ต้นทุนต่อคลิปและภาระ Support รองรับแพ็กเกจที่กำหนดหรือไม่? | Unit economics + support report | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: PO + QA + Ops • หาก No: ขยาย Pilot/แก้บั๊ก ไม่ขยายลูกค้าหรือเปิด Launch

### Gate 8 — Launch readiness

| Check ID | คำถามที่ต้องตอบ Yes | หลักฐาน | ผล Yes/No |
|---|---|---|---|
| G8-01 | Production config, secret, monitoring, alert และ capacity limits พร้อมหรือไม่? | Readiness checklist | ☐ Yes ☐ No |
| G8-02 | Restore drill ผ่าน RPO/RTO ที่ตกลงและไม่มีงานโพสต์ถูก Replay โดยไม่ตรวจหรือไม่? | Restore report | ☐ Yes ☐ No |
| G8-03 | มี Rollback/Kill switch ที่หยุดรับงานใหม่และหยุด Submit โดยไม่ทำให้ผลไม่ชัดเจนหายหรือไม่? | Incident drill | ☐ Yes ☐ No |
| G8-04 | Support runbook ขอบเขตอุปกรณ์ เงื่อนไขบริการและข้อมูลลูกค้าพร้อมเผยแพร่หรือไม่? | Approved runbooks/policies | ☐ Yes ☐ No |
| G8-05 | PO อนุมัติเปิดแบบจำกัดกลุ่มพร้อมเกณฑ์หยุดและผู้รับผิดชอบเฝ้าระบบหรือไม่? | Release sign-off | ☐ Yes ☐ No |

Decision: ☐ Yes ☐ No • ผู้อนุมัติ: PO + Ops • หาก No: ยังไม่เปิดบริการ Production

## 12. Gate register — สถานะ ณ วันที่สร้างเอกสาร

| Phase | Deliverable | อนุมัติผ่าน Yes/No ปัจจุบัน | เหตุผล | ผู้ตัดสินใจ |
|---|---|---|---|---|
| P0 | PRD/UI baseline | No | มี Draft และ UI ตัวอย่าง ยังไม่มี Sign-off | PO |
| P1 | Feasibility | No | ยังไม่มีผล POC แหล่งวิดีโอและโทรศัพท์จริง | PO + Tech Lead |
| P2 | SaaS foundation | No | ยังไม่มีระบบจริงและหลักฐานทดสอบ | Tech Lead + QA |
| P3 | Video production | No | ยังไม่มีระบบผลิตจริงและหลักฐานทดสอบ | Video Lead + QA |
| P4 | Scheduler | No | มีตัวอย่าง UI แต่ยังไม่มี Scheduler จริง | Backend Lead + QA |
| P5 | Agent publishing | No | ยังไม่มี Agent จริงและการตรวจโพสต์จริง | Agent Lead + QA + PO |
| P6 | Billing/Admin | No | ราคาและธุรกรรมยังเป็นตัวอย่าง | PO + Finance + QA |
| P7 | Pilot/UAT | No | ยังไม่เริ่ม Pilot | PO + QA + Ops |
| P8 | Launch | No | ยังไม่มี Readiness sign-off | PO + Ops |

No ในตารางนี้หมายถึง “ยังไม่อนุมัติผ่านเพราะหลักฐานยังไม่ครบ” ไม่ใช่ผลว่าโครงการล้มเหลว

## 13. Critical UAT cases

| Test ID | สถานการณ์ | Expected result | Gate |
|---|---|---|---|
| T01 | ผู้ใช้ A เรียก Job/Device/Clip ของ B | ปฏิเสธทุกเส้นทาง รวมไฟล์ | G2/G7 |
| T02 | Token ถูก Username ผิด | ปฏิเสธ ไม่เผยเจ้าของ | G2 |
| T03 | Reconnect Agent เดิม 20 ครั้ง | จำนวนทะเบียนเท่าเดิม | G2 |
| T04 | เปิดสอง Process installation_id เดียว | มีเพียง Session เดียวที่รับงาน | G2/G5 |
| T05 | Client เปลี่ยน Environment | ไม่เปลี่ยน Scope ฝั่ง Server | G2 |
| T06 | Revoke Token ระหว่าง Idle/ระหว่าง Submit | Idle หยุดรับงาน; Submit ต้องติดตามผล ไม่โพสต์ซ้ำ | G5 |
| T07 | Serial ที่มีเจ้าของแล้วถูกลงทะเบียนอีก | ปฏิเสธหรือใช้กระบวนการโอนที่ยืนยันสิทธิ์ | G2 |
| T08 | ลิงก์ชี้ Private address ผ่าน Redirect | ปฏิเสธก่อนเข้าถึง | G3 |
| T09 | ต้นฉบับสั้นเกินสร้าง 6 คลิป | แจ้งจำนวนจริง ไม่สร้างซ้ำเติมเอง | G3 |
| T10 | Render ล้มเหลวและ Event ซ้ำ | คืน Reservation ครั้งเดียว | G3/G6 |
| T11 | เริ่ม 19:00 ทุก 2 ชั่วโมง Window ถึง 21:00 | รอบถัดไป 09:00 วันถัดไป | G4 |
| T12 | เครื่อง Offline ผ่านสามรอบแล้ว Online | ไม่ Burst ทุกงานทันที | G4 |
| T13 | สอง Series นัดเครื่องเดียวกันเวลาเดียวกัน | แจ้ง Collision/จัดคิว; ไม่มี Claim ซ้ำ | G4 |
| T14 | Pause/Resume และ Cancel หลัง Claim | ตารางที่เหลือชัดเจน งานที่เริ่มแล้วไม่อ้างว่าหยุดสำเร็จโดยไม่มีผล | G4/G5 |
| T15 | โทรศัพท์อยู่บัญชีผิดหรืออ่านชื่อไม่ได้ | NEEDS_ACTION ไม่มีการ Submit | G5 |
| T16 | Caption ไทย อีโมจิ และ Hashtag | ข้อความตรงกับที่อนุมัติ ไม่เสีย Encoding | G5 |
| T17 | Agent หายก่อน Submit | Retry ได้หลังตรวจว่าไม่มี Submission | G5 |
| T18 | Agent หายหลัง Submit ก่อน ACK | UNKNOWN หยุด Retry จนตรวจผล | G5 |
| T19 | Server Restart/Queue redelivery | Attempt เดิมไม่ถูก Submit ซ้ำ | G4/G5 |
| T20 | Webhook ชำระซ้ำ/ปลอม/ผิดลำดับ | ไม่เพิ่มสิทธิ์ซ้ำหรือเปิดสิทธิ์จากรายการปลอม | G6 |
| T21 | งานสองงานใช้โควตาคงเหลือรายการเดียว | อย่างมากหนึ่งงานกันโควตาสำเร็จ | G6 |
| T22 | สมาชิกหมดอายุขณะมีงานรอ/กำลัง Submit | รอถูกพัก; Submit เก็บและตรวจผลต่อ | G6 |
| T23 | Storage cleanup ขณะงานกำลังทำ | ไม่ลบไฟล์ที่งานยังต้องใช้ | G6/G8 |
| T24 | Restore Database จาก Backup | Reconciling งานภายนอกก่อน Replay โดยเฉพาะ SUBMITTING/UNKNOWN | G8 |
| T25 | เปลี่ยน TikTok UI/Agent เวอร์ชันไม่รองรับ | พักงาน แจ้ง Compatibility ไม่กดพิกัดแบบเดาสุ่ม | G5/G8 |

## 14. Risks และ decision register

| Risk / Decision | ผลกระทบ | วิธีจัดการ | Owner / เมื่อใด |
|---|---|---|---|
| ช่องทางโพสต์อัตโนมัติและข้อกำหนดบริการ | เปิดขายไม่ได้ตามรูปแบบที่ตั้งใจ | ตรวจเส้นทางที่เลือกก่อน POC ใช้งานจริงและ Gate 1; หากเปลี่ยนเป็นเตรียมคลิป/ผู้ใช้โพสต์เองให้แก้ Scope และแผน | PO / P1 |
| YouTube/Bilibili เปลี่ยนการเข้าถึง | Download บางชนิดหยุดทำงาน | Adapter แยก Source health และรายการชนิดลิงก์ที่รองรับ | Video Lead / P1–P3 |
| Android/TikTok UI เปลี่ยน | โพสต์ล้มเหลวหรือผิดขั้นตอน | Matrix ที่รองรับ ตัวตรวจสถานะ UI และหยุดเมื่อไม่รู้หน้าจอ | Agent Lead / P1–P5 |
| ไม่สามารถยืนยันผลโพสต์ทุกกรณี | โพสต์ซ้ำเมื่อ Retry | UNKNOWN + ตรวจผลด้วยหลักฐาน + Human resolution | Agent Lead / P5 |
| Token ถูกคัดลอกหรือ installation_id ปลอม | เข้าถึงคิว/ใช้สิทธิ์เกิน | Scope, Session fencing, Rate limit, Revocation; ไม่อ้างว่า installation_id ป้องกันการโคลนได้สมบูรณ์ | Backend / P2 |
| ต้นทุนวิดีโอยาวและ Retry สูง | ราคาขาดทุน | จำกัดนาที/ขนาด/Concurrency วัดต้นทุนจริงและ Cap ต่อ Workspace | PO/Ops / P1/P6 |
| สิทธิ์ใช้วิดีโอ/เพลงไม่ครบ | งานเผยแพร่ไม่เหมาะสม | Declaration/แหล่งที่มา กระบวนการร้องเรียนและพักงาน | PO / P0–P6 |
| ทีมและกำหนดเวลา | แผน 12 สัปดาห์ไม่ตรงทรัพยากร | ยืนยันทีมและ Re-estimate หลัง POC | PM / P0/P1 |

### Decisions ที่ต้องปิดก่อนพัฒนาระยะที่เกี่ยวข้อง

- D01: ชื่อแบรนด์จริง โดเมน และ Owner — P0
- D02: ชนิดลิงก์/ความยาวต้นฉบับ/จำนวนคลิปสูงสุด — P1
- D03: Windows/Android/TikTok versions ที่รองรับ — P1
- D04: รูปแบบและข้อกำหนดช่องทางเผยแพร่ที่เปิดบริการได้ — P1
- D05: ราคาจริง โควตา เครื่อง Agent/Session และกำไรขั้นต้นเป้าหมาย — P6
- D06: ผู้ให้บริการรับชำระ ภาษี เอกสารชำระเงิน Auto-renew และ Refund policy — P6
- D07: Pilot users, Support hours และ Release cohort — P7/P8

## 15. Release และการดูแลหลังเปิด

เริ่มด้วย Cohort ไม่เกิน 10 Workspace และ Capacity cap ตามผล Benchmark ขยายเมื่อเสถียรและมีต้นทุนรองรับ ไม่มีการขยายโดยอาศัยจำนวนผู้สมัครอย่างเดียว

หยุดรับงานโพสต์ใหม่ทันทีเมื่อพบโพสต์ผิดบัญชี ข้อมูลข้าม Workspace โพสต์ซ้ำที่เกิดจากระบบ หรือความผิดปกติของการชำระเงินที่กระทบสิทธิ์ แยก Kill switch สำหรับ Ingest, Render, Scheduling และ Submission เพื่อให้ตรวจผล Attempt ที่เริ่มแล้วต่อได้

Runbook ต้องครอบคลุม Source failure, Render failure, Queue lag, Agent Offline, Token revoke, UNKNOWN post, Payment mismatch, Retention และ Restore ระบุผู้รับผิดชอบและช่องทางแจ้งลูกค้า การส่งข้อความจริงต้องอยู่ในกระบวนการบริการที่ได้รับอนุญาต

## 16. แบบฟอร์ม Gate review ใช้ซ้ำ

| ช่องกรอก | รายละเอียด |
|---|---|
| Phase / Gate | ____________________ |
| Build / PRD version | ____________________ |
| วันที่ตรวจ / Environment | ____________________ |
| Check ID และผล | ____________________ |
| Evidence link / Test report | ____________________ |
| ถ้า No: ทดสอบไม่ผ่านหรือยังไม่ได้ทดสอบ | ____________________ |
| Action owner / Due date | ____________________ |
| ข้อสรุปอนุมัติ Phase | ☐ Yes ☐ No |
| ผู้ตรวจ / ผู้อนุมัติ | ____________________ |

## 17. เอกสารอ้างอิงสำหรับตรวจใน Phase 1

รายการนี้เป็นแหล่งสำหรับตรวจความเข้ากันได้และข้อกำหนดปัจจุบัน ไม่ใช่การยืนยันว่ารูปแบบบริการผ่านการอนุมัติแล้ว

- TikTok Content Sharing Guidelines: https://developers.tiktok.com/docs/en/content-sharing-guidelines
- TikTok Direct Post: https://developers.tiktok.com/docs/en/content-posting-api-get-started
- TikTok Copyright: https://support.tiktok.com/en/safety-hc/account-and-user-safety/copyright
- Android ADB: https://developer.android.com/tools/adb
- yt-dlp supported sites: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
- UIAutomator2: https://github.com/openatx/uiautomator2

บันทึกท้ายเอกสาร: UI ที่มีอยู่เป็น Prototype; PRD และแผนฉบับนี้พร้อมนำไป Review และแตกงานพัฒนา แต่ยังไม่มีผลทดสอบระบบ Production หรือ Gate sign-off
