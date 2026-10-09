# Progress

## Current phase: P7 — Pilot/UAT (staging live; pilot prerequisites open). G0 = Yes, G1 = No (5/6), G2 = Yes (signed 2026-10-09), G3 = Yes, G4 = Yes, G5 = Yes, G6 = No (3/5, PO signed under Q-31), G7 = No (0/5).

Last updated: 2026-10-07

### Latest slice (2026-10-09 22:xx) — clips stay on the Agent's PC (Q-33)
- G2 = Yes (PO signed); PR #8 (Q-32 + G2) open
- PO (Q-33): no clip upload; the Agent keeps clips in a folder chosen at setup; the web shows stills, not video
- Implemented (branch `p7-local-clips`, on top of PR #8): `clipflow_worker.delivery` (checks = server rules, parity unit test; 3-frame JPEG still); migration 0012 (`clips.file_location`, `preview_key`, `agent_path`); `PUT /v1/agent/jobs/{id}/clips/{n}/preview` (JPEG ≤ 2 MB, needs reported checks) = delivered + quota settled; a "passed" without every check ok is stored as failed; `/media` returns the still (`kind`); Agent: `agent/clips_folder.py` (asked at `login`, `set-folder [--move]`, < 5 GB free = no new job), job runner delivers checks + still, post runner reads the chosen folder then the old one (FILE_UNAVAILABLE otherwise, Thai reason on the web); web: still + Agent path + copy, no video player for these clips
- Commands: unit 178 (new delivery 3, clips folder 4), integration 228 / 9 skipped (new API 4; the real Agent pipeline now delivers stills: file_location agent), E2E 17 passed after the PO restarted Docker (new: a clip kept on the Agent shows the real still (810 px), its path and no video player, and can be approved)
- Next: commit/PR; Agent 0.3.0 build (Q-32 + Q-33)

### Previous slice (2026-10-09 20:xx) — clip count from the source (Q-32) + staging release
- Staging: PR #7 merged → Render deployed `8bdd0f6` (/healthz), data kept (1 user, 1 workspace, 1 environment, alembic 0010); rollback in Render = PO next
- PO (Q-32): count follows the source, length in seconds (default 300); whole-source split; over quota → stop for the user
- Implemented (branch `p7-auto-clips`): `segments.tile` (balanced split at pauses, greedy fallback with a last clip up to 1.2x, short tail joined or left out), `pipeline.plan(whole=)`, Agent passes `auto_clips`; migration 0011 (`jobs.auto_clips`, cap 100, expand-only); API `auto_clips` + `clip_length_s` (80–100 %), last-clip limit shared by the event check and the file check; web: length field (default 300) + "คำนวณจากความยาวต้นฉบับ" (default) / "กำหนดเอง", review and job pages show the source-based count
- Found: the first tiling cut always at max length lost the tail (130 s of 2,530 s) → balanced split
- Commands: worker unit 38 (4 new), integration 224 passed / 9 skipped (4 new API + real-pipeline whole split: 4 consecutive clips of a 70 s file, all checks passed), unit 171, E2E 16 (new: default auto count)
- Rollback (PO): /healthz back to the previous build, data kept → G2-05 Yes; PR #8 opened (Q-32 + G2-05)
- G2-01 (PO): min password length 10 + password reset on the public staging URL with a Microsoft 365 mailbox: recover → verify (no failed verify before) → password changed → sign-in with the new one → G2-01 Yes; G2 technical 5/5
- **G2 = Yes**: ปิยศักดิ์ อนุมัติในแชท 2026-10-09
- Next: new Agent build (0.3.0) for Q-32; pilot prerequisites (50 MB file limit, G6-01/G6-02, D07 pilot users)

### Previous slice (2026-10-09 17:xx) — staging image, Render blueprint, rehearsal (G2-05, E-49)
- PO: Render + Supabase punpun
- Implemented: `Dockerfile` (web build → API image, non-root, BUILD_ID), `deploy/start.sh` (migrate → uvicorn, LF via .gitattributes), `.dockerignore`, `render.yaml`, `DB_SCHEMA` (search_path on every connection, alembic in schema, name validated), `OBJECT_STORAGE_REGION`, `WEB_DIST` (SPA on the API origin, API 404s kept), `VITE_API_URL=same-origin`, dashboard-style DB URLs accepted, `/healthz` build id; CI job "Staging image build + smoke"; `tools/staging_rehearsal.py`; `docs/runbooks/staging.md`; Supabase: private bucket `clipflow-media` created (MCP)
- Found: tables in `public` would be readable through Supabase's REST API with the public key → own schema; S3 region was hard-coded us-east-1 → setting; Supabase free = 50 MB per file (clips often larger) → open item before pilot
- Commands: staging rehearsal deploy/release/rollback ok (4.3/2.8/2.8 s, 23 tables in clipflow, 0 in public); `test_staging_image.py` 4 passed
- Gates: G2-05 still No — needs the Render deploy by the PO, then one real release + rollback
- Hosted (PO, 2026-10-09): https://punpun-staging.onrender.com up after a DB password fix; checks from outside + Supabase schema/privileges ok (see G2-05); fixes: build id from RENDER_GIT_COMMIT, HEAD on web routes
- Next: merge the fix = first real release, then Render Rollback → confirm build ids; E-28 sign-up on the public URL

### Previous slice (2026-10-09 15:xx) — dashboard bento (E-47 step 3)
- PR #5 merged (a38cd26) incl. CI fixes: job-runner test allowed encoder-dependent ms at the last pause; axe measured mid-fade after the theme switch → reduced motion + two frames before measuring (probed: colours final at once)
- Implemented (branch `p7-dashboard`): `DashboardPage.tsx` — next post (server time, Bangkok, today/tomorrow, countdown < 24 h, queue of 4), quota meter (used/limit, cycle end, trial/plan), ready phones + missing details, posts waiting for a person, 5 recent jobs, account facts; each card loads separately and refreshes every 30 s; empty account shows the next step on every card; `lib/posts.ts` shares post-state wording with the calendar; old HomePage removed
- Commands: E2E 15 passed (new `dashboard.spec.ts`; quality covers the dashboard with data: axe both themes, 360 px, 200 %), lint/tsc/build ผ่าน
- Environment: Docker Desktop wedged twice more (Kong) → PO restarted
- Step 4 (same PR #6): cursor spotlight on cards (mouse only) + one-time staggered page entrance; reduced motion turns both off; E2E 15 passed (quality alone 2.4 min, same as before)
- Next: G2-05 staging; G2-01 PO items

### Previous slice (2026-10-09 13:xx) — marketing landing page (E-48)
- PO: landing ที่ `/` สำหรับผู้เยี่ยมชม, ไม่แสดงราคา, กลุ่ม SME/ครีเอเตอร์/เอเจนซี่; PR #4 merge แล้ว → เปิด PR #5 สำหรับ `8ae381f` + `a742308`
- Implemented: `LandingPage.tsx`, `landing.css`, route `/` = landing (ไม่เข้าระบบ) / แดชบอร์ด (เข้าระบบ), SEO + OG meta; hero เป็นภาพ UI จริง (โทรศัพท์ 9:16 + การ์ดอนุมัติ + ตารางโพสต์) ไม่ใช่ภาพ stock
- Found + fixed: หัวข้อไทยตัดบรรทัดกลางวลี (ไม่มีช่องว่าง) → จัดกลุ่มวลีไม่ให้แยก; ปุ่มบน nav มือถือขึ้นสองบรรทัด (กฎ a.btn ชนะ) → แก้; การ์ดลอยบังซับในภาพโทรศัพท์ → ย้าย; ภาพหน้าจอ landing ถูกทับโดยแดชบอร์ด (path `/` เดียวกัน) → แยกชื่อ
- Commands: E2E 14 passed (quality: landing ผ่าน axe ทั้งสองธีม, 360px, ซูม 200%; auth: `/jobs` ต้องเข้าระบบ + landing CTA → `/signup`), build + bundle check ผ่าน
- Next: PO ตรวจข้อความ/ภาพ; โดเมนจริง (D01) ก่อนโปรโมต; ขั้น 3–4 ของธีมในแอป

### Previous slice (2026-10-09 12:xx) — UI theme "Linear / Modern" (E-47), steps 1–2
- PO: ให้ `uithem.txt` + เลือก มืดเป็นหลัก/ปุ่มสลับสว่าง, ขั้น 1–2, effect พอดี
- Implemented: `index.css` เขียนใหม่เป็น token (มืด/สว่าง), ปุ่ม/ช่องกรอก/การ์ด/ป้ายสถานะ (จุดเรืองแสง + ข้อความ)/dialog/ตาราง/ปฏิทิน; `ThemeToggle.tsx`; `Shell.tsx` เมนูข้างแบบ sticky + ปุ่มเมนูมือถือ (aria-expanded, Esc, ปิดเมื่อเปลี่ยนหน้า); Inter + IBM Plex Sans Thai; แสงพื้นหลังนิ่ง + grid, แสงเคลื่อนไหวเฉพาะหน้า login; reduced-motion/forced-colors
- Found + fixed: แสงพื้นหลังไม่แสดงเพราะ :root มี background ทำให้ body ทาสีทับ layer z-index -1; พื้นหลัง fixed ทำให้ภาพเต็มหน้าขาดที่ 800px; สี 2 คู่ไม่ผ่าน contrast (hover ปุ่มหลัก 4.2, ขอบช่องกรอก 1.57) → ปรับ
- Commands: `quality.spec.ts` ตอนนี้รัน axe ทั้งธีมมืดและสว่าง + เทสต์เมนูมือถือ/จำธีม — E2E 14 passed, build + bundle check ผ่าน, tsc/lint ผ่าน
- Next: PO ดูหน้าตาแล้วตัดสินใจขั้น 3 (แดชบอร์ด bento) และ 4 (spotlight/entrance)

### Previous slice (2026-10-09 11:xx) — G7-04 consolidated QA (NF-04, NF-09, security)
- Implemented: `test_crud_load.py` + `load_client.py` (NF-04 opt-in: 50 users/60 s, client แยก process); `quality.spec.ts` (NF-09: 15 หน้าด้วยข้อมูลจริง × 360px/ซูม 200%/desktop, axe-core 4.13 WCAG 2.1 AA, keyboard ทั้ง journey + dialog); `@axe-core/playwright` 4.13.0 (pinned); `docs/uat/qa-report.md`
- Found + fixed: ช่องวันเวลา (datetime-local) ไม่มี focus ring — Chromium โฟกัส segment ภายในที่ :focus-visible จับไม่ได้ → global focus rule + :focus-within; ข้อมูลทดสอบชื่อบัญชียาวเกิน 25 ถูกปฏิเสธเงียบ ๆ → ใช้ค่ายาวแต่ถูกต้องและตรวจว่าบันทึกได้; detector ล้นจอถูกพิสูจน์ด้วย element กว้างเกิน
- Commands: CRUD load 2 รอบ p95 629/741 ms (0 errors), E2E 13 passed, npm audit 0, pip-audit 0, ruff/tsc ผ่าน
- ระหว่างทาง: Docker Desktop ค้าง (Kong ไม่ตอบ, หยุด container ไม่ได้) → PO restart แล้ว start ใหม่
- Gates: G7-04 ยัง No — เหลือ NVDA ด้วยคน, มือถือจริง, load บน staging
- Next: staging (G2-05) ปลดล็อกหลายข้อ; PO ทดสอบ NVDA/มือถือจริง

### Previous slice (2026-10-09 08:xx) — G2-01: Gmail SMTP (PO) + E-28 confirm page
- PO ตั้ง Custom SMTP (Gmail) ใน Dashboard เอง; App Password ที่เคยพิมพ์ในแชทแนะนำให้เพิกถอนและสร้างใหม่ — ไม่ถูกบันทึกที่ใดใน repo
- Implemented (E-28): หน้า `/auth/confirm` (กดปุ่มแล้วจึงเรียก `verifyOtp`), template ภาษาไทย `supabase/templates/confirmation.html` + `recovery.html` (local ใช้ผ่าน `supabase/config.toml`), E2E: GET ของตัวสแกนก่อนผู้ใช้ไม่ทำให้ลิงก์เสีย, ลิงก์ reset ที่ใช้แล้ว → หน้าลิงก์หมดอายุ + ขอลิงก์ใหม่
- Commands: E2E 10 passed, tsc/build + bundle check ผ่าน
- Gates: G2 ยัง 3/5 — G2-01 รอ PO วาง template + ตั้ง min length/Site URL + ทดสอบ cloud จริง; G2-05 staging
- Cloud (PO): Gmail SMTP ใช้ได้หลังบันทึก App Password ใหม่ (เดิม 535); reset + สมัครใหม่ → อีเมลไทย → ปุ่มยืนยัน → onboarding สำเร็จ (auth log 10:00–10:04 น.)
- Next: min length 10 ใน Dashboard; staging (G2-05) เพื่อพิสูจน์ E-28 กับตัวสแกนจริง

### Previous slice (2026-10-09 07:xx) — G6 PO sign-off (Q-31) + P7.1 regression T01–T25
- PO: "อนุมัติ G6 ปิยศักดิ์" → บันทึกการลงนามใน G6 แต่ G6 ยังเป็น No (G6-01/G6-02); Q-31: เริ่ม P7 ที่ทำในเครื่องได้, ห้ามขาย/รับเงินจริง/Pilot
- Implemented: `docs/uat/p7-uat.md` (T01–T25 → เทสต์ที่พิสูจน์แต่ละข้อ + หลักฐานจริงที่มี); `test_uat.py`: T01 sweep ทุก route ที่รับ id (B ได้คำตอบเหมือน id ที่ไม่มี และข้อมูล A ไม่เปลี่ยน), T14 ยกเลิกหลัง claim, T19 server restart (process ที่สองบน DB เดียวกัน), T22 หมดอายุระหว่างรอ/Submit, T23 retention ขณะงานกำลังทำ; unit T15 อ่านชื่อบัญชีไม่ได้
- Found + fixed (T22, Medium): โพสต์ที่ถูกปฏิเสธตอน Submit เพราะหมดอายุถูก park เป็น NEEDS_ACTION ต่างจากรายการที่ยังไม่ claim ซึ่งรอ → ตอนนี้กลับไปรอ (SCHEDULED) และทำต่อหลังต่ออายุ
- Commands: integration 213 passed / 8 skipped, unit 167, E2E 10, ruff ผ่าน
- Gates: G7 0/5 (G7-03 บางส่วน: 24/25 ผ่าน, T24 = P8); Pilot ต้องรอ G2 + D07
- Next: P7 ที่ไม่ต้องมี Pilot (รายงาน QA รวม: mobile/a11y/security) หรือ G2-01/G2-05 เพื่อปลดล็อก Pilot; Omise/Stripe (G6-02); ราคา (G6-01)

### Previous slice (2026-10-09 05:xx) — P6 slice B: admin, audit, support, retention; D05/D06 answers
- PO: D05 "config ได้ทีหลัง"; D06 Omise + Stripe (config ทีหลัง), **ไม่คืนเงินทุกกรณี** — บันทึกใน decisions, แสดงในหน้าแพ็กเกจ/ชำระ
- Implemented: migration 0010 (platform_role, audit reason/details, clips.file_deleted_at), `deps.staff/admin_only`, `routers/admin.py` (workspaces, jobs by ID, payments, plans + new version, plan/extend/end/quota with reason + before/after audit, retention run), `retention.py`, `manage.py` (grant-role, retention), quota grant/deduct, `/v1/me` platform_role, storage.delete, preview 410 หลังลบ; เว็บ `/admin` (เมนูเห็นเฉพาะ staff)
- Found: `quota._add` ใช้ rowcount ที่ไม่น่าเชื่อถือ → บอกว่าไม่ได้บันทึกทั้งที่บันทึกแล้ว (เดิมไม่มีใครใช้ค่าคืน) → ใช้ RETURNING; grant ทำให้ "ใช้" ติดลบ → แยก grant เป็นเพดานเพิ่ม; เทสต์ admin สร้าง plan version ใหม่ในฐานข้อมูลที่ใช้ร่วมกัน → คืนค่าเดิมหลังเทสต์
- Commands: integration 208 passed / 8 skipped (ใหม่ 7 `test_admin.py`), unit 166, E2E 10 (ใหม่ `admin.spec.ts`), ruff/tsc ผ่าน, dev DB → 0010
- Gates: G6 3/5 Yes (G6-03, G6-04, G6-05); G6-01 รอราคา/โควตาจริง + ต้นทุน, G6-02 รอ adapter Omise/Stripe
- Next: adapter Omise/Stripe เมื่อได้บัญชี (D06), ตั้งราคา (D05); P7 UAT/launch readiness; G2-01/G2-05

### Previous slice (2026-10-09 03:xx) — P6 slice A: sandbox billing, subscription cycles
- Implemented: migration 0009 (ราคาตัวอย่างบน plans, รอบสมาชิก, payments, payment_events, quota period = รอบ), `billing.py` (E-45: effective/roll, checkout, HMAC webhook, dedupe, สถานะเดินหน้า, grant/refund), routes `/v1/billing/plans|subscription|checkout|payments|webhooks/{provider}|sandbox/{id}/simulate`; onboarding = trial 30 วัน; สร้างงานต้องมีรอบที่ใช้งานได้; dispatch รอเมื่อหมดอายุ; เว็บ `/billing` (แพ็กเกจ, รอบ, โควตา, ประวัติ) + `/billing/sandbox/:id` (ผู้ให้บริการจำลอง)
- Found: quota key แบบวันที่ทำให้ trial กับรอบที่จ่ายวันเดียวกันใช้โควตาร่วมกัน → ใช้เวลาเริ่มรอบเต็ม; downgrade migration ลบแพ็กเกจที่ subscription ยังอ้างอิง → ย้ายกลับ trial ก่อน
- Commands: integration 201 passed / 8 skipped (ใหม่ 8 `test_billing.py`), E2E 9 (ใหม่ `billing.spec.ts`), dev DB → 0009 (ย้ายข้อมูลเดิมแล้ว), ruff/tsc ผ่าน
- Gates: G6 2/5 Yes (G6-03, G6-04); G6-01/G6-02 รอ D05/D06; G6-05 = slice B
- Next: P6 slice B (Admin/Audit/Support/Retention)

### Previous slice (2026-10-09 01:xx) — G5-06 fencing in the posting path + needs-action list (P5.7)
- Implemented: `test_post_fencing.py` (revoke ระหว่างโอนไฟล์ → Agent หยุด + ลบไฟล์ + token ใหม่ทำต่อ; session เก่าของการติดตั้งเดียวกันถูกตัด; session หมดอายุ; revoke หลังกดโพสต์ → UNKNOWN); `GET /v1/schedule-items?attention=true` (ทุกโพสต์ที่รอคน: NEEDS_ACTION/UNKNOWN ทุกวันที่); หน้า `/schedule` มีกล่อง "ต้องดำเนินการ" พร้อมเหตุผลภาษาไทยและลิงก์ไปจัดการ; `Shop.token_id` ใน test helpers
- Commands: integration 193 passed / 8 skipped (ใหม่ 4 fencing + 1 attention), unit 166, E2E 8, ruff/oxlint/tsc ผ่าน
- Gates: **G5 = Yes** — PO ปิยศักดิ์ อนุมัติในแชท 2026-10-09 (6/6)
- Next: P6 billing/admin (D05/D06 ยัง Open — sandbox เท่านั้น); G2-01/G2-05 ก่อน release

### Previous slice (2026-10-09 00:xx) — authorized real post (Q-30): G5-04 + G5-05
- PO: "อนุญาตโพสต์ใหม่ 1 ครั้ง" → Q-30; harness รับเฉพาะ decision ที่บันทึกว่า Accepted + "1 โพสต์"
- ระหว่างทาง: คำสั่งที่บันทึก Q-30 ถูก guard ของ PowerShell บล็อกทั้งคำสั่ง จึงไม่ได้รัน แต่ผมรันเช็กด้วย Q-29 ต่อ — harness เดิมทำงานจริง เปิด TikTok แล้วหยุดที่หน้า splash ก่อนเริ่มโพสต์ (โพสต์ไม่ได้อยู่แล้ว: grant Q-29 หมด); แก้ account() ให้รอ SplashActivity
- ผล (5 นาที 49 วินาที): โพสต์ 1 ครั้ง "เฉพาะคุณ" บน @patsy4404 → Agent จำลองดับหลังกด → Server UNKNOWN ไม่ส่งซ้ำ → ตรวจบนเครื่อง: วิดีโอส่วนตัว 1 → 2, marker `cfc6f1c8` → resolve → VERIFIED_SUCCESS; Gboard คืน, ไม่เหลือไฟล์, Q-30 ใช้แล้ว
- Gates: G5 5/6 Yes (G5-01..G5-05); เหลือ G5-06
- Next: G5-06 (revoke token/หมดสิทธิ์ระหว่างโพสต์ end-to-end), P5.7 หน้า needs-action ฝั่ง Agent

### Previous slice (2026-10-08 22:xx) — Q-28/Q-29, authorized post attempt, P5.1/P5.6 packaging
- PO: Q-28 (G5-03 ไม่ต้องทดสอบ login/CAPTCHA กับแอปจริง), Q-29 (อนุญาต 1 โพสต์); เพิ่มสิทธิ์ `Edit/Write(services/api/tests/**)`
- บัญชีผิดบนแอปจริง → ACCOUNT_MISMATCH หยุดก่อนเปิดคลิป
- โพสต์จริง (Q-29): `agent/authorization.py` (grant ครั้งเดียว บันทึกก่อนกด), `TikTokUi.submit/verify_private_post/private_count`, post runner โหมด live (+ จำลองดับหลังกดโพสต์), `test_authorized_real_post.py`. ผล: รอบ 1 อ่านบัญชีไม่ได้ (แก้: account() ลองซ้ำ), รอบ 2 หน้าจอเปลี่ยนระหว่างกด (แก้: ลองใหม่), จำนวนวิดีโอส่วนตัวอ่านครั้งแรกได้ 0 (แก้: อ่านจนสองครั้งตรงกัน), **รอบ 3 session หมดอายุระหว่างขั้น TikTok → grant ถูกใช้ก่อน Server ปฏิเสธ SUBMITTING → หยุดก่อนกดโพสต์; ไม่มีโพสต์เกิดขึ้น (วิดีโอส่วนตัวยัง = 1), สิทธิ์ Q-29 หมด** — แก้: ตรวจ session (heartbeat) ก่อนใช้ grant + test, harness มี heartbeat; ไม่ได้ reset ledger เอง (ต้องให้ PO อนุญาตใหม่)
- P5.1/P5.6: `agent/updater.py`, `agent/credentials.py` (DPAPI), `agent/compat.py` (D03 matrix), `agent/admin.py` (login/logout/status/install/rollback + log), `agent/__main__.py`, `tools/build_agent.py`; จริงบน Windows 11: install 0.2.0 → self-update 0.2.1 → rollback 0.2.0, SHA ผิด/โพสต์ค้างถูกปฏิเสธ, exe เห็นโทรศัพท์จริง; พบและแก้ "Access is denied" หลัง smoke test (retry)
- Commands: unit 166, integration 188 / 8 skipped (opt-in), bundle test (opt-in) ผ่าน, ruff ผ่าน
- Gates: G5 3/6 Yes (G5-01, G5-02, G5-03); G5-04/G5-05 รอสิทธิ์โพสต์ใหม่; G5-06 บางส่วน
- Next: PO อนุญาตโพสต์ใหม่ 1 ครั้ง → รัน `test_authorized_real_post.py`; G5-06 revoke ระหว่างโพสต์; P5.7 fault tests + หน้า needs-action

### Previous slice (2026-10-08 20:xx) — P5.4 TikTok UI up to Post (Q-27)
- PO: "อนุญาต" (Q-27) + เพิ่มสิทธิ์ `PowerShell(adb *)`, `Edit/Write(agent/**)` ใน settings (auto-mode classifier เคยปฏิเสธการเปิด TikTok และการเขียน adapter)
- สำรวจบนเครื่องจริงทีละขั้น (Profile → share sheet → editor → post screen → visibility → caption) แล้ว force-stop; สิ่งที่พบบันทึกใน runbook
- Implemented: `agent/tiktok_ui.py` (อ่านบัญชี, share intent, Video → ถัดไป, เฉพาะคุณ, พิมพ์ไทยผ่าน ADBKeyboard + ตรวจตรงทุกตัว + คืน IME, login/CAPTCHA/หน้าไม่รู้จัก → หยุด, ปฏิเสธโพสต์/Story/แบบร่าง/Shop ในตัว + ตรวจใต้จุดกดทุกครั้ง); `agent.cli ui-rehearsal`; post runner `--ui-rehearsal` (บัญชีผิด/CAPTCHA → NEEDS_ACTION)
- Real device: `ui-rehearsal` บน POCO — บัญชี @patsy4404 ตรง, เฉพาะคุณ, แคปชันไทย+emoji+แฮชแท็กตรง, ไม่กดโพสต์, TikTok ปิด, Gboard คืน, ไม่เหลือไฟล์
- Commands: unit 158 (ใหม่ 11 `test_tiktok_ui.py`), integration 182 / 7 skipped (ใหม่ 3 ซ้อม TikTok ใน post runner), ruff ผ่าน
- Gates: G5 1/6 Yes (G5-02); G5-03 บางส่วน (ทดสอบบัญชีผิด/login/CAPTCHA กับแอปจริงต้องขออนุญาต)
- Next: P5.1/P5.6 แพ็กเกจ/ติดตั้ง/อัปเดต Agent; ขั้น Submit จริง (P5.4 ส่วนสุดท้าย) ต้องขออนุญาตโพสต์แยก (G5-05)

### Previous slice (2026-10-08 17:xx) — real-phone dry run + P5.5 reconciliation
- Real device: `test_real_device_post.py` บน POCO 25078PC3EG / Android 15 — claim → ดาวน์โหลด + ตรวจ hash → push_verified → Gallery → DRY_RUN_DONE → ลบไฟล์ทดสอบ, 6.1 วินาที, ไม่เปิด TikTok (สรุปใน var/evidence/p5_real_device_dry_run.json)
- Implemented: `posts.resolve` / `posts.retry` (E-43) + routes `/v1/schedule-items/{id}/resolve`, `/retry`; item ส่ง `attempts`, `evidence`; เว็บ: dialog "ยืนยันผล…" (ไม่มีตัวเลือกเริ่มต้น, ต้องมีหลักฐาน) และปุ่ม "แก้แล้ว ลองใหม่"; `ConfirmDialog` ใช้ id เฉพาะต่อ dialog (เดิมทุก dialog ใช้ id เดียวกัน) + `confirmDisabled`; fixture `live_client` ย้ายไป conftest
- Found: เทสต์ปฏิทินพังเป็นบางครั้ง — สอง series เวลาเท่ากันไม่มีลำดับแน่นอน (calendar/claim) → เรียงตามเวลาที่สร้างเป็นตัวตัดสิน; รันซ้ำ 3 รอบผ่าน
- Commands: integration 179 passed / 7 skipped (ใหม่ 6 `test_resolution.py`), E2E 8, ruff/oxlint/tsc ผ่าน; dialog ยืนยันผลยังไม่มี E2E (E2E server เป็น dry-run จึงสร้าง UNKNOWN ไม่ได้ — ตรรกะทดสอบผ่าน API)
- Gates: G5 0/6 Yes — G5-02, G5-04, G5-06 บางส่วน
- Next: P5.4 (ต้องได้รับอนุญาตแตะ UI TikTok), P5.1/P5.6 แพ็กเกจ/ติดตั้ง/อัปเดต Agent

### Previous slice (2026-10-08 16:xx) — P5.2/P5.3 Agent post runner (dry-run)
- Implemented: `agent/post_runner.py` (E-42: claim ทุก 15 วินาทีเมื่อว่าง → ไฟล์ของตัวเองหรือดาวน์โหลด+ตรวจ SHA-256 → push_verified → Gallery → DRY_RUN_DONE → ลบไฟล์ทดสอบ; journal ก่อนทุกขั้น; LEASE_LOST หยุดทันที); ServerClient `claim_post`/`post_event`/`download`; `run_connection` รับหลาย worker; `agent.cli connect` เปิด post runner โดยค่าเริ่มต้น (`--no-posts`); `Adb.push_verified(remote_name=)`; test storage ใช้พอร์ตเดียวกับ server จริง (ดาวน์โหลดผ่าน HTTP ได้จริงในเทสต์)
- Commands: integration 173 passed / 7 skipped (ใหม่ 6 `test_agent_post_runner_http.py` กับโทรศัพท์จำลอง: ไฟล์ของตัวเอง, ดาวน์โหลด+ตรวจ hash, ไฟล์เสียระหว่างโอน, Gallery ไม่เจอ, lease หลุดระหว่างโอน, ไม่มีโทรศัพท์พร้อม); unit 147; ruff ผ่าน
- **ยังไม่ได้รัน**: `test_real_device_post.py` (opt-in) — โทรศัพท์ QA ไม่ได้เสียบอยู่ (`adb devices` ว่าง)
- Gates: G5 0/6 Yes — G5-02, G5-06 บางส่วน
- Next: เสียบ POCO → รัน dry-run จริง; P5.4 (ตรวจบัญชี TikTok, ใส่ข้อความไทย, หยุดเมื่อเจอ login/CAPTCHA — ต้องได้รับอนุญาตแยกก่อนแตะ UI TikTok), P5.5 resolve UNKNOWN, P5.1/P5.6 ติดตั้ง/อัปเดต

### Previous slice (2026-10-08 15:xx) — P4.5 dispatch load test + P4.6 schedule calendar
- Implemented: `test_dispatch_load.py` (opt-in `CLIPFLOW_LOAD=1`); `GET /v1/schedule-items?start&end` (ทุก series, เวลานัด/เวลาจริงแยกกัน, `queued_behind`, `delay_s`); หน้า `/schedule` รายสัปดาห์ + รายการ (เมนู "ตารางโพสต์")
- Commands: load test: 150 โทรศัพท์ / 300 โพสต์ → 100% ภายใน 60 วินาที, p95 14.3 วินาที, 0 error (E-41); integration 167 passed / 6 skipped (load test เป็น opt-in); unit 147; E2E 8 (schedule journey ตรวจหน้าปฏิทิน); ruff/oxlint/tsc/build ผ่าน
- Found: load test รอบแรกมี error 356 ครั้ง — สาเหตุคือ harness ล็อกอิน Agent ตอน setup แล้วรอหลายนาทีจน session หมดอายุ (TTL 90 วินาที) ไม่ใช่ Server; แก้ให้ล็อกอินตอน Agent เริ่ม (เหมือน `agent.cli connect`)
- Gates: **G4 = Yes** — PO ปิยศักดิ์ อนุมัติในแชท 2026-10-08 (5/5)
- Next: P5 Agent ฝั่งโพสต์ (dry-run บนโทรศัพท์จริงผ่าน claim → transfer → gallery → DRY_RUN_DONE, poll ≤ 15 วินาที), resolve UNKNOWN

### Previous slice (2026-10-08 14:xx) — P4.4 pause/resume (server preview) + edit unstarted posts
- Implemented: `schedules.shift_plan/apply_shift` (เลื่อนรักษาระยะ — ใช้ร่วมกับนโยบายออฟไลน์), `pause`, `resume_plan`/`resume` (expected_version), `edit_item` (version, อนาคต, Window, คงลำดับคลิป); routes `/v1/schedules/{id}/pause`, `/resume/preview`, `/resume`, `PATCH /v1/schedule-items/{id}`; เว็บ: ปุ่มหยุดชั่วคราว/ทำงานต่อ (dialog แสดงการเลื่อนจาก Server), แก้เวลารายการ; test helpers ย้ายไป `conftest.py` (`real_clip`, `shop`) และ `api_test_shop.py`
- Commands: integration 166 passed / 5 skipped (ใหม่ 5 `test_schedule_changes.py`), E2E 8 passed (schedule journey + pause/resume/แก้เวลา), ruff/oxlint/tsc ผ่าน
- Found: ข้อความ error เก่าค้างหลังแก้เวลาสำเร็จ (เห็นใน screenshot) — แก้ให้ล้างเมื่อสำเร็จ + E2E ตรวจ
- Gates: G4 4/5 Yes (G4-01..G4-04); เหลือ G4-05
- Next: P4.5 load test dispatch (95% ≤ 60 วินาที) + P4.6 หน้าตารางรายสัปดาห์/รายการ แสดงเวลานัดเทียบเวลาจริง

### Previous slice (2026-10-08 13:xx) — P4.3 claims, device lock, leases, late-post policy (dry-run)
- Implemented: migration 0008 (lease/attempts/evidence + `schedule_item_events`), `posts.py` (E-40: expire leases, offline defer/skip สำหรับโพสต์ที่พลาด, claim ทีละเครื่อง + `dispatchable`, state machine CLAIMED→…→DRY_RUN_DONE / SUBMITTING→VERIFYING→VERIFIED_SUCCESS|UNKNOWN, ตรวจการอนุมัติซ้ำก่อน SUBMITTING, หลักฐานผลโพสต์), routes `/v1/agent/posts/claim`, `/v1/agent/posts/{id}/events`; `create_app(posting_mode=...)` — Server ที่รันจริงเป็น dry-run เสมอ ไม่มี env เปิด live; เว็บแสดงสถานะโพสต์ภาษาไทย
- Commands: integration 161 passed / 5 skipped (ใหม่ 9 `test_posts.py`: ทีละเครื่อง, 2 Agent แย่งกันผ่าน HTTP จริง, lease หลุดก่อน/หลัง Submit, แก้ข้อความระหว่างเตรียม → ปฏิเสธตอน Submit, หลักฐาน, defer/skip โพสต์ที่พลาด); ruff/tsc ผ่าน
- Found: เทสต์ยืนยันว่า Agent ใหม่บน installation เดิมทำให้ session เก่าหมด (fencing ตามออกแบบ) — ปรับลำดับในเทสต์
- Gates: G4 2/5 Yes (G4-01, G4-03)
- Next: P4.4 pause/resume + แก้รายการ, P4.5 load test, P4.6 หน้าปฏิทิน; Agent ฝั่งโพสต์ (dry-run บนโทรศัพท์จริง) = P5

### Previous slice (2026-10-08 12:xx) — P4.1/P4.2 schedules (Q-26) + G3-05
- Implemented: `slots.py` (คำนวณเวลา, E-39), migration 0007 (`schedule_series`, `schedule_items` ผูกเวอร์ชันที่อนุมัติ), `schedules.py` (preview/create/cancel, ผูกเวอร์ชัน, sync เมื่อการอนุมัติเปลี่ยน, `dispatchable`), routes `/v1/schedules/preview`, `/v1/schedules` (+idempotency), `/v1/schedules/{id}`, `/cancel`, `/v1/schedule-items/{id}/cancel`; hook ใน clips (แก้/อนุมัติ/ยกเลิกอนุมัติ) และ devices (ยกเลิกการผูก → NEEDS_ACTION); เว็บ: ส่วน "ตั้งเวลาโพสต์" ในหน้ารายละเอียดงาน (preview จาก Server, ยืนยัน, ตาราง, ยกเลิก); `e2e/agentSim.ts`
- Commands: unit 147 passed (ใหม่ 21 `test_slots.py`), integration 152 passed / 5 skipped (ใหม่ 15 `test_schedules.py` รวมสองโทรศัพท์แย่งคลิปพร้อมกันผ่าน HTTP จริง), E2E 8 passed (ใหม่ `schedule.spec.ts`), ruff/oxlint/tsc/build ผ่าน
- Found: preview เคยจัดคิวรายการใหม่ไว้ก่อนรายการเดิมเมื่อเวลาเท่ากัน — แก้ให้รายการที่ตั้งไว้ก่อนได้ก่อน
- Gates: **G3 = Yes** — PO ปิยศักดิ์ อนุมัติในแชท 2026-10-08 (5/5); G4 1/5 Yes (G4-01)
- Next: P4.3 Agent claim + device lock (เรียก `dispatchable`, dry-run), P4.4 pause/resume/offline, P4.5–P4.6

### Previous slice (2026-10-08 11:xx) — G3-01: SSRF guard (T08) + render resource limits
- Implemented: `clipflow_worker/netguard.py` (E-38: guard ต่อ thread ที่ตรวจทุกการ resolve ชื่อโฮสต์ระหว่างดาวน์โหลดต้นฉบับ รวม redirect); `source.inspect/download`, `pipeline.plan/fetch_part` ใช้ guard; URL ที่ส่งให้ ffmpeg ตรวจก่อน; error ใหม่ `SOURCE_BLOCKED_ADDRESS` (+ ข้อความไทยบนเว็บ); `render.RenderLimits` (thread ≤ ครึ่ง CPU, priority ต่ำบน Windows, timeout); สแกนเสียง timeout 30 นาที
- Commands: worker + unit 126 passed (ใหม่ 12 ใน `test_netguard.py`: redirect ผ่าน yt-dlp จริง → ปลายทางภายในได้ 0 request, guard ต่อ thread, URL สำหรับ ffmpeg, pipeline.plan ถูก guard, render timeout/threads); YouTube จริงใต้ guard: plan + range download ผ่าน (116 วินาที); ruff/oxlint/tsc ผ่าน
- Integration 137 passed, 5 skipped (opt-in) — รวม T08 ผ่าน job runner: งานลิงก์ที่ต้นฉบับพาไปที่อยู่ภายใน → FAILED `SOURCE_BLOCKED_ADDRESS`, เซิร์ฟเวอร์ภายในได้ 0 request, ไม่จองโควตา (Docker Desktop เคยหยุดระหว่าง session; PO เปิดใหม่แล้ว)
- Gates: G3 4/5 Yes (G3-01 Yes); G3-05 รอ P4
- Next: P4 scheduler (G3-05) — G3 ยัง No จนกว่า G3-05 + sign-off

### Previous slice (2026-10-08 10:xx) — P3.4 web: create job, job list, job detail, preview, text edit, approval
- Implemented: `/create` (3 ขั้น: ต้นฉบับ → รูปแบบ → ตรวจและสร้าง; ตรวจ input ทีละขั้น, idempotency key ต่อฟอร์ม, auto mode ต้องติ๊กยืนยัน, แสดงโควตาที่จะใช้; ขั้นเลือกเครื่อง/เวลา = P4), `/jobs` (แท็บ ทั้งหมด/กำลังผลิต/รอตรวจ/ต้องดำเนินการ/ล้มเหลว, refresh 5 วินาทีขณะมีงานกำลังผลิต), `/jobs/:id` (timeline, ข้อผิดพลาดพร้อมวิธีแก้ภาษาไทย, notice, โควตาจอง/ใช้/คืน, seed, ยกเลิกงานพร้อมยืนยัน; ต่อคลิป: preview ลิงก์ 5 นาที, ผลตรวจไฟล์, ช่วงต้นฉบับ, ชื่อในวิดีโอ (แก้ไม่ได้), แก้ caption/hashtags แบบมีเวอร์ชัน, อนุมัติ/ยกเลิกอนุมัติ); `e2e/helpers.ts` มี `agentSession`; CI e2e ติดตั้ง ffmpeg
- Fixed: ผลตรวจไฟล์ที่เปิดไม่ได้เคยส่งข้อความ ffprobe ที่มี path ชั่วคราวของ Server (มีชื่อผู้ใช้ Windows ของ Server) ไปให้ลูกค้า → ตอนนี้ส่งข้อความกลาง (`mediacheck.py`, test ใน `test_clips.py`)
- Commands: E2E 7 passed (ใหม่ 2: สร้างงานผ่าน wizard → Agent จำลองส่งคลิปจริง 1080×1920 + ไฟล์เสีย → preview เล่นได้ใน Edge ยาว 35 วินาที → แก้ข้อความ → อนุมัติ → แก้อีกครั้งการอนุมัติหลุด → อนุมัติใหม่; ลิงก์ผิด/ยกเลิกงาน); clip tests 11 passed; tsc + build + bundle check ผ่าน; ruff/oxlint ไม่มี error
- Gates: G3 3/5 Yes — G3-03 = Yes: PO ดูและฟังคลิปจริง 2 คลิปแล้ว "okay" (2026-10-08); G3-05 ยังรอ P4
- Next: T08 + render limits (G3-01); P4 scheduler (G3-05; หลัง G3 หรือ override)

### Previous slice (2026-10-08 09:xx) — P3.3 Agent job runner
- Implemented: `agent/job_runner.py` (E-37: claim → วิเคราะห์ → source_validated → ดาวน์โหลดช่วง → render → clip_rendered → อัปโหลด → completed; keep-alive `progress`; หยุดเมื่อ LEASE_LOST/JOB_NOT_ACTIVE; resume หลัง restart), `clipflow_worker/pipeline.py` (P1 pipeline เป็นขั้นตอนที่ใช้ซ้ำ; POC CLI ใช้ตัวเดียวกัน), ServerClient: claim/event/upload; `agent.cli connect --media-dir/--no-jobs`; Server: event `progress`, spec มีรายการคลิปที่รายงานแล้ว, คลิปที่ยังไม่อัปโหลดรายงานใหม่ได้
- Commands: integration 136 passed, 5 skipped (opt-in) — ใหม่ 6 tests ของ runner บนไฟล์วิดีโอจริงที่ ffmpeg สร้าง (หยุดเสียงทุก 10 วินาที → ตัดตรงกลางช่วงเงียบ); opt-in YouTube จริง (P1 corpus `PBES5k67dhI`, 101 นาที): READY_FOR_REVIEW 2 คลิป 3:51/4:06 ผ่านการตรวจ, โควตา 2/2, 9.8 นาที — สรุปใน var/evidence/p33_real_source.json; unit 114; ruff ผ่าน; POC `produce --file` ยังทำงาน
- Found: เทสต์ที่เรียก runner โดยไม่มี heartbeat ทำให้ session หมดอายุ 90 วินาทีระหว่างดาวน์โหลดเสียง — ของจริงใช้ heartbeat แยก thread (`run_connection`); ต้นฉบับที่มีซับฝังในภาพ ต้องสร้างงานด้วย subtitles=false
- Gates: G3 2/5 Yes (G3-02, G3-04); G3-03 รอ PO ดูคลิปจริง (var/evidence/p33_real_clips/)
- Next: P3.4 หน้าเว็บ สร้างงาน/รายการงาน/รายละเอียด + preview + แก้ข้อความ + อนุมัติ; T08 + render limits (G3-01)

### Previous slice (2026-10-08 07:xx) — P3.2 clip delivery, checks, preview, metadata, approval
- Implemented: migration 0006 (clip file/check/approval columns, clip_metadata); `storage.py` (S3/MinIO + local), `mediacheck.py` (ffprobe), `clips.py` (accept_upload, metadata versions, approve/unapprove, auto policy); routes: `PUT /v1/agent/jobs/{id}/clips/{n}/file`, `/v1/clips/{id}` (detail + history), `/media` (ลิงก์ 5 นาที), `PATCH /metadata`, `/approve`, `/unapprove`, `/v1/media/...` (local signed); โควตาหักเมื่อไฟล์ถึงและ hash ตรง; `completed` ต้องอัปโหลดครบ (E-36)
- Commands: integration 128 passed, 4 skipped (opt-in); clip tests 11 ผ่านด้วยไฟล์ 1080×1920 H.264/AAC จริงจาก ffmpeg; MinIO presigned test ผ่าน (private bucket ปฏิเสธลิงก์ไม่ลงชื่อ 403); unit 114; ruff ผ่าน; dev DB → 0006; API (8000) ใช้ MinIO แล้ว
- Gates: G3 0/5 Yes — G3-03, G3-05 บางส่วนเพิ่ม
- Next: P3.3 Agent job runner (claim → ดาวน์โหลด/ไฟล์ → วิเคราะห์ → render → อัปโหลด) ด้วย pipeline P1 + ทดสอบกับต้นฉบับจริง

### Previous slice (2026-10-08 06:xx) — Q-25 phone check on Agent start
- PO: เมื่อเปิด Agent ให้ตรวจ serial โทรศัพท์ ส่งไปเช็กที่ Server ถ้าไม่มีให้ลงทะเบียน และแจ้งให้ไปใส่รายละเอียดในระบบหลังบ้าน
- Implemented: `agent/device_registry.py` `DeviceSync` + `describe()` (ข้อความไทย), `run_connection(on_session=…)` เรียกตอนเข้าระบบและทุก 60s, `agent.cli connect` เปิดใช้เป็นค่าเริ่มต้น (`--no-phone-check` ปิด); API register ตอบ `missing_details` + `details_url`; `/v1/devices` มี `missing_details`; เว็บ: ป้าย "ต้องใส่รายละเอียด", `?edit=<id>` เปิดฟอร์ม
- โทรศัพท์จริง (POCO 25078PC3EG): เปิด Agent loop → "ลงทะเบียนโทรศัพท์ 25078PC3EG (TST8…) แล้ว — กรุณาไปใส่รายละเอียด … ที่ http://localhost:5173/devices?edit=…" ✓
- Bug ที่ test จับได้: รอบตรวจซ้ำ 1 นาทีถัดไปพิมพ์ข้อความเตือนซ้ำ (REGISTERED → ALREADY_REGISTERED) → นับเป็นสถานะเดียวกัน
- Commands: unit 114 passed; integration 116 passed, 3 skipped; real-device 2 passed; E2E 5 passed; ruff ผ่าน

### Previous slice (2026-10-08 05:xx) — P3.1 jobs + quota ledger
- PO override Q-24: เริ่ม P3 ทั้งที่ G2 = No (G2-01, G2-05 ค้าง)
- Implemented: migration 0005 (jobs, job_events, clips, quota_ledger, plans.clips_per_month); `/v1/jobs` สร้าง (idempotency key, ตรวจลิงก์/ชื่อไฟล์, rights Q-14, seed, review/auto ต้องยืนยัน) / รายการ / รายละเอียด / ยกเลิก; `/v1/agent/jobs/claim` + `/events` (E-35); `/v1/workspace/usage.clips`
- Bug ที่ test จับได้: งานที่ Agent รับแล้วแต่ยังเป็น RECEIVED ถูก Agent ตัวที่สองรับซ้ำได้ → claim ดูจาก lease ไม่ใช่ state
- Commands: integration 114 passed, 3 skipped; quota race ×3 ผ่าน; unit 111 passed; ruff ผ่าน; `alembic check` no drift; dev DB → 0005
- Gates: G3 = 0/5 Yes (G3-01/02/04 บางส่วน)
- Next: P3.2 อัปโหลดคลิป (MinIO, ตรวจ sha256) + preview URL อายุสั้น + metadata version + อนุมัติ (G3-05)

### Previous slice (2026-10-08 04:xx) — CI green on GitHub
- PO ล็อกอิน GitHub (Git Credential Manager ใน Terminal panel) → push `master` ขึ้น `piyasak/puppun` (private) สำเร็จ, ตั้ง upstream `origin/master`
- **CI รอบแรกผ่านทั้งหมด (สีเขียว)** — PO ยืนยันในแชต; Claude ดูหน้า Actions ของ repo private ไม่ได้ (browser pane ไม่ได้ล็อกอิน)
- PO ทดลอง `agent.cli connect` กับ cloud เอง: เชื่อมต่อได้ (Environment `mainx`), heartbeat ครบ
- Gates: G2 = 3/5; G2-05 เหลือ staging deploy/rollback; G2-01 เหลือ dashboard/E-28/SMTP
- Next: PO เลือกที่ตั้ง staging

### Previous slice (2026-10-08 03:xx) — CI workflow (G2-05 partial)
- PO ให้ remote: https://github.com/piyasak/puppun.git
- Implemented: `.github/workflows/ci.yml` (E-34); ruff config ใน `pyproject.toml` + แก้ lint 84 จุด (ไม่มีบั๊กจริง; `poc.py` lambda ผูกตัวแปรรอบให้ชัด); `tasks.py lint|typecheck|build` ใช้งานได้; Playwright ใช้ Chromium บน Linux
- Commands: `py tasks.py lint` → ผ่าน (oxlint warning 5 จุด set-state-in-effect); `py tasks.py typecheck` → ผ่าน; Python job ใน container Linux → ruff ผ่าน, integration 84 passed, unit 110 passed + 1 ที่ล้มเพราะไม่ได้ copy `apps/` เข้า container
- Blocked: `git ls-remote` → "Invalid username or token" (credential ใน Git Credential Manager ใช้กับ GitHub ไม่ได้) และ API ตอบ 404 (repo private หรือยังไม่มี) → ต้องให้ PO ล็อกอิน GitHub บนเครื่องนี้ และยืนยันชื่อ repo (`puppun` vs แบรนด์ `punpun`)
- ก่อน push: เอกสารที่ commit แล้วมีอีเมลบริษัทของ PO และชื่อบัญชี TikTok ทดสอบ — ถ้า repo เป็น public ควรลบออกก่อน
- Next: PO ยืนยัน repo + ล็อกอิน → push → ดูผล CI จริง; เลือกที่ตั้ง staging

### Previous slice (2026-10-08 02:xx) — P2.6 device registration
- Current phase: P2
- Implemented: migration 0004 (devices + partial unique index on active serial); `/v1/agent/devices/register|report`; `/v1/devices` list/edit (ชื่อเรียก, บัญชี TikTok ที่คาดหวัง)/unbind; in_use.device_limit; Agent: `agent/device_registry.py` (hardware serial ผ่าน getprop, ไม่ใช้ id ของ Wi-Fi ADB), `python -m agent.cli register-devices`; เว็บ: เมนูโทรศัพท์ (สถานะพร้อม/ยังไม่อนุญาต/ไม่พบ/Agent ออฟไลน์ + วิธีแก้, แก้ไข, ยกเลิกการผูกพร้อม dialog)
- **โทรศัพท์จริง**: POCO 25078PC3EG ลงทะเบียนผ่าน Agent → HTTP → API สำเร็จ, ซ้ำ idempotent, Workspace อื่นผูกไม่ได้ (`CLIPFLOW_REAL_DEVICE=1`, อ่าน getprop เท่านั้น)
- Commands: `py tasks.py test-integration` → 84 passed, 3 skipped (opt-in live/real-device); real-device test → 1 passed; `py tasks.py test-unit` → 111 passed; `py tasks.py test-e2e` → 5 passed; build + bundle check ผ่าน; `alembic check` no drift; dev DB → 0004
- Gates: **G2-04 → Yes**; G2: 3/5 (G2-02, G2-03, G2-04); เหลือ G2-01 (dashboard/E-28/SMTP) และ G2-05 (CI/staging)
- Next: P2.7 — CI (lint/typecheck/test/build) + staging deploy/rollback (G2-05); ต้องการการตัดสินใจเรื่องที่ตั้ง staging

### Previous slice (2026-10-08 01:xx) — P2.5 Agent sessions
- Current phase: P2
- Implemented: migration 0003 (agent_installations, agent_sessions); `/v1/agent/authenticate|heartbeat|session/end` (E-31); `/v1/agents` list + deregister; revoke/rotate token จบ session ทันที; `/v1/workspace/usage.in_use`; ลด limit ต่ำกว่าที่ใช้ไม่ได้; rate limit sign-in ของ Agent; Agent: `agent/identity.py` (installation_id, process lock), `agent/server_client.py`, `python -m agent.cli connect` (token จาก env/prompt ไม่ผ่าน argv); เว็บ: เมนู Agent (สถานะออนไลน์/ขาดการติดต่อ/ออฟไลน์, ยกเลิกทะเบียนพร้อม dialog), Environments แสดง "ใช้อยู่"
- Commands: `py tasks.py test-integration` → 65 passed, 2 skipped (live Supabase opt-in); race 5 installs ×3 ผ่าน; `py tasks.py test-unit` → 108 passed; `py tasks.py test-e2e` → 4 passed; `alembic check` no drift; dev DB → 0003
- Bug พบ+แก้ (E-32): `npm run build` ที่ไม่มี env ผ่าน แต่ bundle ไม่มีโค้ดแอป → build ต้องมี env + ตรวจ bundle
- Gates: **G2-03 → Yes**; G2-02 Yes; G2-01/04/05 No
- Next: P2.6 ลงทะเบียนโทรศัพท์ (Serial ผ่าน Agent, ownership conflict, device cap) → G2-04

### Previous slice (2026-10-08 00:xx) — P2.3 Environment limits + P2.4 Agent tokens
- Current phase: P2
- Implemented: migration 0002 (plans + subscriptions + Environment limits + agent_tokens); แพ็กเกจ Demo `trial` (E-29) ให้ทุก Workspace ตอน onboarding; Environment limits = การจัดสรรจากแพ็กเกจ ตรวจผลรวมใต้ล็อก subscription; `/v1/workspace/usage`; Agent token generate/list/revoke/rotate + `verify()` สำหรับ P2.5 (E-30); เว็บ: เมนู Environments (การใช้แพ็กเกจ, สร้าง/แก้ไข) และ Agent Token (แสดงครั้งเดียว + คัดลอก, rotate/ยกเลิกพร้อม dialog ยืนยัน)
- Commands: `py tasks.py test-integration` → 46 passed, 1 skipped (live token); race test ×5 ผ่าน; `alembic check` no drift; dev DB → 0002; `py tasks.py test-e2e` → 3 passed; `npm run build` ผ่าน
- Bug ที่ test จับได้: secret base64url มี `_` ได้ → ห้าม split ด้วย `_`; server parse ด้วย regex ความยาวคงที่ (test แก้ให้ใช้ regex เดียวกัน)
- Gates: **G2-02 → Yes** (server/web); G2-03 บางส่วน (limits) — No; G2-01/04/05 No
- Next: P2.5 Agent authenticate/heartbeat/session fencing (T02–T05) → ปิด G2-03

### Previous slice (2026-10-07 23:xx) — cloud sign-up verified by PO
- **Cloud จริง (PO, 2026-10-07 22:09–22:10 น.)**: สมัครด้วยอีเมลบริษัท → Supabase ส่งอีเมลยืนยัน (`mail.send` confirmation) → PO กดลิงก์ → `user_signedup` + login (implicit) → API `/v1/me` 403 ONBOARDING_REQUIRED → `POST /v1/onboarding` 201 → `/v1/me` 200; DB: users.id = Supabase user id, role owner, rights 2026-10-07, audit `account.onboard` พร้อม request_id. **ข้อค้นพบ**: ระบบสแกนอีเมลของ Microsoft 365 (IP 104.47.x / 57.155.x) เปิดลิงก์ยืนยันเองหลังผู้ใช้ 14 วินาที → ได้ 'One-time token not found' — ถ้าตัวสแกนเปิดก่อนผู้ใช้ ลิงก์จะใช้ไม่ได้ (ต้องแก้ E-28). Reset บน cloud ยังไม่ได้ทดสอบ (มีใน E2E local แล้ว)

### Previous slice (2026-10-07 23:xx) — web auth screens + Playwright E2E
- PO: ทดสอบด้วย Playwright + อีเมลจริง (confirm เอง) → Claude สมัครบัญชี/พิมพ์รหัสผ่านบนบริการภายนอกไม่ได้ จึงตกลงทำ 2 แบบ: (1) E2E อัตโนมัติบน Supabase local (2) PO ทดสอบเองบน cloud ผ่านหน้า localhost
- ใหม่ `apps/web` (React 19 + TS 6 + Vite 8, supabase-js 2.117, react-router 7): หน้า สมัคร / เข้าสู่ระบบ / ลืมรหัสผ่าน / ตั้งรหัสใหม่ / ตั้งค่าบัญชี (onboarding + คำรับรองสิทธิ์) / แดชบอร์ด (ข้อมูลจาก `/v1/me`) — ภาษาไทย, โทนน้ำเงิน, label + error inline, dark mode, mobile
- ใหม่ Supabase local (`supabase/config.toml`, ES256, confirm email, min 10, Mailpit) + `py tasks.py test-e2e` → **2 passed** (Edge)
- `npm run build` ผ่าน (tsc + vite), `oxlint` 1 warning (fast-refresh)
- Cloud: API (8000) + web (localhost:3000) ชี้ไป `punpun` รันอยู่ รอ PO สมัครด้วย piyasak_s@boonrawd.co.th และ confirm เอง — อีเมลจะส่งถึงเฉพาะเมื่ออีเมลนี้เป็นสมาชิกทีมของ org ใน Supabase (ข้อจำกัดตัวส่งพื้นฐาน)

### Previous slice (2026-10-07 22:xx) — E-25 = Supabase → browser auth on Supabase Auth (E-27)
- PO: E-25 ใช้ Supabase; เลือก "ย้าย Auth ไป Supabase" + สร้างโปรเจกต์ใหม่ `punpun` (ap-southeast-1, Free, $0/เดือน ยืนยันแล้ว) → สร้างแล้ว ref `wqcbubphiihpseqzglwe`
- เปลี่ยน: ลบ register/login/logout/reset/session cookie/CSRF/Argon2/dev outbox ออกจาก API; เพิ่ม `identity.py` (ตรวจ Supabase JWT ด้วย JWKS, ES256/RS256 เท่านั้น), `POST /v1/onboarding`, `users.id` = Supabase user id; migration 0001 เขียนใหม่ (ยังไม่เคย commit/deploy; ล้าง dev DB ที่มีแต่ข้อมูล smoke แล้ว migrate ใหม่)
- Commands: `py tasks.py test-integration` (+ `CLIPFLOW_SUPABASE_URL`) → 28 passed, 1 skipped (ไม่มี live token); `alembic check` → no drift; uvicorn + JWKS จริง: healthz 200, token ปลอม 401; `test-unit` → 92 passed
- PO ต้องทำ: ตั้งค่า Supabase dashboard (confirm email, min length 10, Site URL/redirect) และทดสอบสมัคร→ยืนยัน→เข้า→reset ด้วยอีเมลสมาชิกทีม (Claude สร้างบัญชีบนบริการภายนอกเองไม่ได้) — `docs/runbooks/supabase-auth.md`
- Open: SMTP สำหรับ production (ตัวส่งพื้นฐานของ Supabase ส่งได้เฉพาะสมาชิกทีม)

### Previous slice (2026-10-07 22:xx) — P2.1 Auth/Workspace + migration baseline
- Current phase: P2 (PO override Q-22)
- Implemented: `services/api` (FastAPI) — register (Workspace + Owner + rights acceptance Q-14), login (email/username), logout, password reset request/confirm, `/v1/me`, Environments CRUD แบบ tenant-scoped; Argon2id; session cookie HttpOnly + CSRF ผูก session; error format `code/message/request_id`; `X-Request-ID`; audit events; Alembic `0001`
- Changed files/modules: `services/api/**`, `tasks.py` (`migrate`, `test-integration`), `.env.example`, docs (G2, decisions E-21..E-26, requirements-map, compatibility)
- Commands run: `py tasks.py test-integration` → 23 passed (Postgres 16.15 จริง, DB ชั่วคราว); `py tasks.py migrate` → 0001 (head); `alembic check` → no drift; HTTP smoke ผ่าน uvicorn (register 201, cross-tenant 404, no CSRF 403, request id echo); `py tasks.py test-unit` → 92 passed
- FR/NF/Gate: FR-01, NF-01, NF-02 (บางส่วน), NF-08 (บางส่วน); G2-01, G2-05 (บางส่วน)
- Checks passed: backend ของ G2-01; migration ส่วนของ G2-05
- Checks No — not tested / blocked: G2-01 (หน้าเว็บ, อีเมลจริง E-25, rate limit), G2-02..G2-04 (ยังไม่ทำ), G2-05 (CI/staging)
- Open decisions: E-25 ผู้ให้บริการอีเมล; Q-21 marker; D01 โดเมน
- Next concrete task: P2.3–P2.4 — Environment limits + plan-wide caps (transactional) และ Agent Token lifecycle (generate/copy once/expire/revoke/rotate + log scan) → G2-02/G2-03

### Previous slice (2026-10-07 21:xx) — power saving (Q-23)
- ใหม่ `agent/power.py`: เปิด Wi-Fi + รอ VALIDATED ก่อนงาน; ปิดแอป + Wi-Fi หลังผลจบ (ไม่ปิดระหว่าง SUBMITTING/VERIFYING/UNKNOWN หรือเมื่อ ADB ผ่าน Wi-Fi); `agent.cli power status|on|off`; dry-run ใช้ power saving เป็นค่าเริ่มต้น
- BUG แก้: ตัวตรวจ online อ่านทั้ง dumpsys → online=true ขณะ Wi-Fi ปิด → อ่านเฉพาะ Current Networks (+ regression test จากข้อความจริง)
- เครื่องจริง: run A (เริ่มเปิด) และ run B (เริ่มปิด) ผ่าน; Wi-Fi เปิดคืนหลังทดสอบ; tests 92 passed

### Previous slice (2026-10-07 20:4x) — P2 authorized
- PO override Q-22: เริ่ม P2 ได้ แม้ G1-06 (ต้นทุน) ยังเป็น No — G1 ยังบันทึกเป็น No
- Next: P2 slice แรก — FastAPI + SQLAlchemy/Alembic บน Docker Postgres, Auth/Workspace + tenant repository + cross-tenant tests (FR-01, NF-01, G2-01)

### Previous slice (2026-10-07 20:3x) — Gate 0 approved
- **G0 = Yes** — ปิยศักดิ์ สุทธิประภา อนุมัติ Gate 0 (2026-10-07)
- G1-03 → Yes ตาม PO override (1 รุ่นพอสำหรับ P1); D03 = เฉพาะ POCO 25078PC3EG / Android 15 / TikTok 40.0.0
- **G1 = No (5/6)** — เหลือ G1-06 ต้นทุน (PO ให้เลื่อนไว้, Q-18) → P2 ยังเริ่มไม่ได้ตามลำดับ Gate จนกว่า PO จะทำ G1-06 หรือสั่ง override

### Previous slice (2026-10-07 20:0x) — authorized test post
- PO: walkthrough ok → **G0-02 Yes**; ไม่มีงบแยก + ทุกบทบาท = ปิยศักดิ์ สุทธิประภา → **G0-05 Yes**; G0 technical 5/5 — **รอ PO sign-off Gate 0**
- ADBKeyboard ติดตั้งแล้ว (ต้องเปิด Xiaomi "Install via USB" + "USB debugging (Security settings)" ก่อน)
- โพสต์ทดสอบจริง 1 ครั้ง (เฉพาะฉัน) บน @patsy4404: แคปชันไทย+emoji ตรง, crash หลังกดโพสต์ → UNKNOWN (ไม่ retry) → resolve ด้วยหลักฐาน → VERIFIED_SUCCESS → **G1-04 Yes**; G1-03 ผ่าน 1/2 รุ่น
- Findings: `input tap` ทะลุ bottom sheet ไปเปิด Shop → ใช้ press 120ms + ตรวจ screenshot ทุกขั้น; uiautomator dump ค้างหลังเปลี่ยน activity; ปุ่ม "Story ของคุณ" โพสต์ทันที — ห้ามกด (`docs/runbooks/tiktok-posting-poc.md`)
- โทรศัพท์สะอาด (ลบไฟล์ทดสอบ), IME คืนเป็น Gboard; โพสต์ทดสอบยังอยู่ (Agent ไม่ลบ — ผู้ใช้ลบเองได้)
- Gates: G0 5/5 technical (sign-off pending), G1 4/6 (G1-03 รุ่นที่ 2, G1-06 deferred)

### Previous slice (2026-10-07 19:3x) — first real phone
- PO: G1-02 ภาพ+ข้อความไทย okay → **G1-02 Yes**; อนุมัติ PRD v1.1 (ปิยศักดิ์ สุทธิประภา, 7/10/2026) → **G0-01 Yes**; D01 แบรนด์ = punpun, โดเมนรอ; owner/งบ/เวลา walkthrough ยังไม่ได้รับ
- โทรศัพท์ 25078PC3EG (Android 15, TikTok trill 40.0.0): `doctor` ผ่าน; `dry-run` ส่งไฟล์+SHA-256+Gallery ผ่าน (68 MB 9s / 158 MB 14s)
- Fault tests จริงก่อน Submit: ADB หลุด → RETRYABLE_FAILED; Agent crash → `agent.cli recover` (ใหม่) → RETRYABLE_FAILED
- BUG แก้ (E-20): `adb push` orphan เขียนไฟล์ที่ไม่ได้ตรวจ hash ลงโฟลเดอร์ Gallery → push ผ่าน staging `.incoming/*.part` + rename หลังตรวจ hash; ทดสอบซ้ำบนเครื่องจริงผ่าน
- ยังไม่ได้ทำ (รออนุญาต): ติดตั้ง helper พิมพ์ไทย, โพสต์ทดสอบจริง/ตรวจบัญชี; ยังไม่มีโทรศัพท์รุ่นที่ 2
- Gates: G0 3/5, G1 3/6 — ทั้งคู่ No; tests 78 passed

### Previous slice (2026-10-07 night)
- PO: Q-15 = ข2 (ดาวน์โหลด/วิเคราะห์/render บน Agent), Q-17 ฟังก์ชันไฟล์ที่ลูกค้าโหลดมาเอง, G1-02 "เสียง okay", G1-03/04 รอเครื่อง QA, G1-06 เลื่อน (Q-18); P0 sign-off/D01/owner/งบ — ยังไม่ได้รับข้อมูล
- ใหม่: `produce --file` (`local_source.py`: ffprobe validation, 8 GB cap, SHA-256 source ID, ไม่เก็บ path, sidecar .srt) — ทดสอบจริง 3/3 จากไฟล์ 61 นาที
- ใหม่: `SOURCE_RATE_LIMITED` + cool-down ต่อแพลตฟอร์ม (`cooldown.py`, 1→2→4→6 ชม.) — แก้บั๊ก bot check (apostrophe โค้ง) ที่ถูกรายงานเป็น "เข้าถึงไม่ได้"
- BUG แก้: ต้นฉบับแนวตั้งถูกดาวน์โหลดที่ 480×852 (กรองด้วย height) → จำกัดด้านสั้นแทน; ตรวจจริงทั้ง 3 orientation
- YouTube ใช้ได้อีกครั้งหลัง ~2.5 ชม.: PBES5k67dhI 3/3 คลิป 3–5 นาที
- Tests: 78 passed; G1 = 2/6 (No)

### Previous slice (2026-10-07 evening, after commit 483714f)
- Network ใช้ได้อีกครั้ง (proxy หาย): link set 2 อ่านได้ 5/5 → รวม 10/10 → **G1-01 Yes**
- D02 จากต้นฉบับจริง: Bilibili 3/3 (183–244s), YouTube 2/3 (191s, 262s)
- BUG พบและแก้: range download ที่ไม่ครบ (33s แทน 231s) ไม่มี error และถูกรายงานว่าสำเร็จ → เพิ่มการตรวจความยาว range (±1s, retry 1 ครั้ง) และ render (±0.5s, RENDER_MISMATCH); ทดสอบกับไฟล์เสียจริงแล้ว; +1 unit test (65 passed)
- ความเสี่ยงใหม่ R-01: YouTube bot check หลังดาวน์โหลดหลายครั้งจาก IP เดียว — รอ PO ตัดสินใจ
- Bash tool ใน session นี้หา `grep/git/env` ไม่เจอ — ใช้ PowerShell แทน

### Previous slice (2026-10-07, after commit 5ed272e)
- PO answers recorded: Q-05/Q-06 confirmed (parallel across devices, queue per device), D02 = random 3–5 min clips per link, Q-12 subtitle toggle, Q-13 phone helper install on QA machine, Q-14 terms review waived + rights accepted once at signup (user override, PO owns the risk)
- Defaults changed: clip length 180–300s; source resource cap 4h (E-17)
- Bug fixed: download errors containing "page" were misclassified as SOURCE_NOT_ACCESSIBLE (bare marker "age"); network/proxy errors now DOWNLOADER_ERROR "retryable"; ANSI colour codes stripped from user-facing details (+4 regression tests)
- D02 verified offline: 3 non-overlapping 180–300s clips selectable from real audio of all 5 sources; synthetic 300s render OK (236s render time)
- Blocker: network now goes through `ssproxy.boonrawd.co.th:8080` returning 407 → link set 2 (YT 3, Bili 2) and real 3–5 min clips **not tested**
- Gates: G0-04 → Yes; G1-05 → Yes (PO decision, Q-14); others unchanged No
- `py tasks.py test-unit` → 64 passed

### Implemented
- P0 (2026-10-06): docs baseline, gate register, `check-gate` — ดู history ด้านล่าง
- PO answers recorded (2026-10-06): Q-01 ไม่แปลซับ, Q-04 Asia/Bangkok, Q-07 ยอมรับ, D04 ADB ก่อน + ต้องรองรับ API ภายหลัง; Q-05/Q-06 บันทึกการตีความ (รอยืนยัน) — `docs/decisions.md`
- Local infra: `docker-compose.yml` (Postgres 16, Redis 7, MinIO + private bucket) — ขึ้น healthy จริง
- P1.1 Source adapter `services/worker/clipflow_worker/source.py`: allowlist https YouTube/Bilibili, ปฏิเสธ IP/credential/port, SSRF guard สำหรับ media URL ที่ adapter คืนมา, error classes แยก (UNSUPPORTED_URL / SOURCE_NOT_FOUND / SOURCE_NOT_ACCESSIBLE / SOURCE_LIMIT_EXCEEDED / DOWNLOADER_ERROR), retry จำกัด 2 ครั้ง, duration fallback ด้วย ffprobe (Bilibili ไม่ส่ง duration)
- P1.2 ทดสอบลิงก์จริง 5/5 (Bilibili 3, YouTube 2) — `docs/compatibility.md`
- P1.3 Produce pipeline (`poc.py`): captions (เฉพาะภาษาต้นฉบับ) → audio-only download → silencedetect (threshold ปรับอัตโนมัติ, E-11) → seeded selection → ดาวน์โหลดเฉพาะช่วง → render 9:16 (libass, Thai wrap, title band, ending card, ซับเปิด/ปิดได้) → manifest.json (seed, intervals, template version, render sha256, probe, timings); `report.py` สรุปเป็นตาราง
- P1.4 (บางส่วน) `agent/adb.py`: devices/doctor/push + on-device SHA-256/MediaStore discovery; `agent/cli.py` devices|doctor|dry-run (หยุดก่อน TikTok UI, ไม่มีคำสั่ง live-post)
- P1.6 (logic) `agent/attempt.py`: write-ahead journal, recovery ก่อน/หลัง SUBMITTING, resolve ต้องมีหลักฐาน+ผู้ตัดสิน
- `tasks.py setup` (สร้าง .venv + ติดตั้ง worker), `test-unit` รวม root + worker tests

### Changed files/modules (this slice)
docker-compose.yml, tasks.py, CLAUDE.md, services/worker/{pyproject.toml, clipflow_worker/{source,media,segments,textlayout,render,poc,report}.py, tests/test_poc_units.py}, agent/{adb,attempt,cli}.py, tests/unit/test_agent.py, docs/{decisions,compatibility,requirements-map,progress,backlog}.md, docs/gates/{G0,G1}.md

### Commands run and actual results
| Command | Result |
|---|---|
| `winget install Gyan.FFmpeg` | FFmpeg 9.0.2 installed |
| `docker compose up -d` | postgres/redis/minio healthy; bucket private |
| `poc inspect` ×5 links | 5/5 OK (Bilibili duration ต้องใช้ ffprobe fallback) |
| `poc produce` ×5 sources (tpl v1) | 15/15 clips, ทุกไฟล์ 1080×1920 H.264/AAC |
| `poc produce` rerun seed เดิม ×2 | intervals ตรงกัน 2/2; render hash ตรงกัน Bilibili, ไม่ตรง YouTube |
| `poc produce` tpl v2 ×2 sources | 4 clips; ตรวจภาพ: title ไม่ทับ watermark/เนื้อหา, ไม่มีซับซ้อน |
| `py tasks.py test-unit` | 60 passed |
| `py tasks.py check-gate 0` / `1` | valid; G0 1/5 Yes, G1 0/6 Yes; both decision No |
| `python -m agent.cli devices` | `[]`, exit 1 — ไม่มีโทรศัพท์ |

Bugs found and fixed during the slice: check-gate crash on cp874 console; yt-dlp ไม่เห็น ffmpeg (symlink + per-process cache) ; caption-boundary selection ใช้ไม่ได้กับ Thai auto captions (เปลี่ยนเป็น audio pause); silencedetect -35 dB ไม่เจอ pause ในต้นฉบับพากย์ (adaptive threshold); manifest บันทึก threshold ผิด; Thai wrap ทิ้งตัวอักษรเดี่ยว; title ทับ watermark และซับซ้อนกับซับฝังในต้นฉบับ (tpl v2)

### FR/NF/Gate IDs covered
FR-02, FR-03, FR-04, FR-05, FR-06, FR-07 (partial), FR-15/17/18 (logic only), NF-03 (partial); G1-01..G1-06 evaluated

### Checks passed
- G0-03 (technical)

### Checks No — failed
- G0-04 — รอยืนยันการตีความ Q-05/Q-06

### Checks No — not tested / blocked
- G0-01, G0-02, G0-05 — PO sign-off, walkthrough, owners/budget, ลิงก์เพิ่ม, โทรศัพท์
- G1-01 ลิงก์ไม่ครบ 5/แพลตฟอร์ม • G1-02 ยังไม่มี human playback QA • G1-03/G1-04 ไม่มีโทรศัพท์ • G1-05 ยังไม่มี terms review • G1-06 ยังไม่มีต้นทุนเป็นเงิน/D02

### Open decisions
D01, D03, D05–D07; Q-02 (AI text), Q-09 (UI prototype), Q-10 (rights text wording for the one-time acceptance); E-17 source cap confirmation

### Next concrete task
0. เมื่อ network ออกได้: `poc inspect` ชุดลิงก์ที่ 2 + `poc produce` (3–5 นาที) อย่างน้อย 1 แหล่งต่อแพลตฟอร์ม → อัปเดต G1-01/G1-02
1. เมื่อโทรศัพท์เชื่อมต่อ: `.venv/Scripts/python -m agent.cli doctor --serial <S>` แล้ว `dry-run --file var/poc_v2/.../clip_01.mp4` (ไม่โพสต์) → บันทึก matrix
2. บนเครื่อง QA (Q-13): ติดตั้ง helper สำหรับกรอกภาษาไทย → ทดสอบ Thai/emoji input (T16)
4. Human playback QA ของคลิปใน `var/poc_v2/` (G1-02); ลิงก์ทดสอบเพิ่ม (G1-01)
5. เปลี่ยนฟอนต์เป็น Noto Sans Thai (E-13) ก่อนใช้ใน P3

---
### History
- 2026-10-06 P0: repository assessment (มีเพียง PRD + docx), docs baseline, gate register 47 checks, check-gate tool + tests
