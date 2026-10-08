# Requirements map (FR / NF → module → test → gate)

สถานะ Impl: `—` ยังไม่เริ่ม • `WIP` • `Done (logic)` ผ่าน unit/integration แต่ยังไม่มีหลักฐาน live • `Done (live)` มีหลักฐานจริงตาม Gate
คอลัมน์ Test เป็นชื่อชุดทดสอบที่ **วางแผน** ไว้ (ยังไม่มีไฟล์จนกว่าจะระบุ path)

## Functional requirements

| ID | Pri | Requirement (ย่อ) | Module(s) | Planned tests / UAT | Gate | Phase | Impl |
|---|---|---|---|---|---|---|---|
| FR-01 | P0 | สมาชิก/Workspace, reset ไม่เปิดเผยบัญชี | Supabase Auth (E-27), api/identity, api/onboarding, web/auth | test_auth, test_tenant_isolation, test_supabase_live, T01 | G2-01 | P2 | WIP — สมัคร/เข้า/reset = Supabase Auth; API ตรวจ JWT ด้วย JWKS + `/v1/onboarding` (Workspace + rights Q-14) + `/v1/me`; tests ผ่าน; หน้าเว็บ auth (`apps/web`) + Playwright E2E บน Supabase local 2/2 ผ่าน; ทดสอบ cloud ด้วยอีเมลจริง (PO) และ Custom SMTP ยังไม่มี |
| FR-02 | P0 | รับลิงก์, allowlist, limit, rights declaration | api/jobs, worker/source | test_source_validation, test_ssrf, T08 | G1-01, G3-01 | P1/P3 | WIP — ลิงก์: allowlist/https/no-IP/no-credentials; ไฟล์ของลูกค้า (Q-17): `local_source.py` ตรวจ regular file, ≤8 GB, ffprobe ต้องเจอ video+duration, SHA-256 เป็น source ID, ไม่เก็บ path เต็ม; ทดสอบจริงกับไฟล์ 61 นาที; rights acceptance (Q-14) = P2; หน้า `/create` เลือกลิงก์หรือไฟล์บนเครื่อง Agent (ชื่อไฟล์เท่านั้น) (P3.4) |
| FR-03 | P0 | ดาวน์โหลด + metadata, แยกสถานะข้อผิดพลาด, retry จำกัด | worker/source (yt-dlp adapter) | test_source_errors, source compatibility report | G1-01, G3-01 | P1/P3 | WIP — error classes แยก (SOURCE_RATE_LIMITED, UNSUPPORTED_FILE, SOURCE_NOT_FOUND); bot check → cool-down ต่อแพลตฟอร์ม 1→6 ชม. (`cooldown.py`, Agent ใช้ใน job runner); range ไม่ครบ → retry 1 ครั้ง; event/upload retry 3 ครั้งด้วย event_id เดิม; 10/10 real links read; งานจริง YouTube ผ่าน Agent (P3.3) |
| FR-04 | P0 | คัดช่วง + random มี seed/template version | worker/analysis | test_segment_selection_reproducible | G3-02 | P3 | WIP — audio-pause boundaries + seeded selection (`segments.py`, E-11); Agent ใช้ seed ของ Server; seed เดิม → ช่วงเดิม + ไฟล์ hash เดิม (`test_agent_job_runner_http.py`) |
| FR-05 | P0 | ประเมินจำนวนคลิปได้จริง แจ้งก่อนใช้โควตา | worker/analysis, api/jobs | test_insufficient_content, T09 | G3-04 | P3 | WIP — Agent ส่ง `possible_clips` จากการเลือกช่วงจริงก่อนจองโควตา; ไม่พอ → ลดจำนวน + `INSUFFICIENT_SOURCE`, 0 คลิป = FAILED ไม่คิดโควตา (T09 ผ่านทั้ง Server และ Agent จริง); แสดงบนเว็บ = P3.4 |
| FR-06 | P0 | Render MP4 9:16 + เสียง, probe | worker/render | test_render_probe, MP4 samples | G1-02, G3-03 | P1/P3 | WIP — Agent render 9:16 ด้วย P1 pipeline (`pipeline.py`) แล้วอัปโหลด; Server ตรวจด้วย ffprobe + preview ลิงก์ลงชื่อ; YouTube จริง 2 คลิปผ่าน; รอคนตรวจภาพ/เสียง (G3-03) |
| FR-07 | P0 | Title/Ending/Caption/Hashtag/ซับ แก้ไขได้ มี version | worker/text, api/clips, web/job-detail | test_metadata_versioning, Thai glyph review | G1-02, G3-03 | P1/P3 | WIP — Agent ส่ง title/caption/hashtags จาก template ภาษาไทยคงที่ (Q-02 ยังไม่ตัดสินเรื่อง AI); caption + hashtags แบบมีเวอร์ชัน, ชื่อคลิปอยู่ในวิดีโอ → RERENDER_REQUIRED; หน้า `/jobs/:id` แก้ caption/hashtags แบบมีเวอร์ชัน (E2E) |
| FR-08 | P0 | Review mode / Auto mode | api/clips, scheduler | test_approval_boundary | G3-05 | P3 | WIP — อนุมัติผูก metadata version + sha256; review ต้องมีคน; auto ต้องยืนยันตอนสร้างงาน และอนุมัติเฉพาะคลิปที่ผ่านการตรวจทุกข้อ; การกันไม่ให้โพสต์คลิปที่ไม่อนุมัติ = P4; หน้าเว็บ: เลือกโหมดตอนสร้างงาน (auto ต้องติ๊กยืนยัน), อนุมัติ/ยกเลิกอนุมัติต่อคลิป, แก้ข้อความหลังอนุมัติ = ต้องอนุมัติใหม่ (E2E) |
| FR-09 | P0 | Schedule ทุก X ชม. จากเวลานัดล่าสุด | scheduler/core | test_schedule_core (PRD examples), T11 | G4-01 | P4 | WIP — X เป็นจำนวนเต็ม 1–168 (UI: 1/2/3/6/12/24), ช่องถัดไป = เวลานัดก่อนหน้า + X (`slots.py`, `test_slots.py`), preview บน Server |
| FR-10 | P0 | Window [start,end) + IANA tz, เก็บ UTC | scheduler/core | test_schedule_window_boundaries | G4-01 | P4 | WIP — เก็บ UTC + IANA timezone; Window [เริ่ม, สิ้นสุด) วันเดียว, 24:00 = สิ้นวัน; MVP รองรับเฉพาะ Asia/Bangkok (E-39) |
| FR-11 | P0 | Offline skip/defer, ไม่ burst, collision | scheduler | test_offline_no_burst, test_collision, T12, T13 | G4-02, G4-03 | P4 | WIP — ชนบนเครื่องเดียวกันเข้าคิว (Q-05), ครั้งละ 1 โพสต์ต่อเครื่อง; โพสต์ที่พลาด >60 นาที → defer รักษาระยะ / skip (ไม่ยิงรวด) (`posts.py`, `test_posts.py`) |
| FR-12 | P0 | Token generate/copy once/expiry/revoke/rotate, hash only | api/agent_tokens, web/connection | test_token_lifecycle, log scan, T02 | G2-02 | P2 | Done (server/web) — `agent_tokens.py` + router: generate/แสดงครั้งเดียว/expiry/revoke/rotate, hash-only, verify (username ไม่ตรง → ปฏิเสธแบบไม่เปิดเผย); UI `TokensPage`; 13 tests + E2E; Agent credential store = P5 |
| FR-13 | P0 | Environment: registered_agent_limit แยก concurrent_session_limit, plan cap รวม | api/environments | test_env_limits_concurrent, T05 | G2-03 | P2 | Done (P2) — limits 3 ค่า + ผลรวม ≤ แพ็กเกจ (transactional, race tests), Agent/Session/โทรศัพท์บังคับตอนลงทะเบียน, ลดต่ำกว่าที่ใช้ไม่ได้, `/v1/workspace/usage` (caps/allocated/in_use), UI Environments; แพ็กเกจ Demo (E-29) — ค่าจริงรอ D05 |
| FR-14 | P0 | installation_id คงที่, reconnect ไม่เพิ่มทะเบียน, fencing | api/agent_auth, agent/identity | test_reconnect_20x (T03), test_duplicate_session (T04) | G2-03, G5-06 | P2/P5 | Done (server + Agent client) — `agent_sessions.py` + `/v1/agent/*` (authenticate/heartbeat/end, fencing by generation), `/v1/agents` (presence, deregister); `agent/identity.py` (installation_id คงเดิม, process lock), `agent/server_client.py` + `agent.cli connect`; T02–T05 ผ่าน (API, HTTP, E2E); T06 (revoke ระหว่าง Submit) = P5 |
| FR-15 | P0 | Serial registration ผ่าน Agent, ownership conflict | api/devices, agent/adb | test_device_ownership, T07 | G2-04 | P2 | Done (P2) — `devices.py` + `/v1/agent/devices/register| Done (P2 + Q-25) — `devices.py` + `/v1/agent/devices/register|report` (ตอบ `missing_details` + `details_url`), `/v1/devices` (list/edit/unbind); Agent: `DeviceSync` ตรวจโทรศัพท์ตอนเปิดและทุก 60s, ลงทะเบียนเครื่องใหม่ + แจ้งให้ไปใส่รายละเอียด; ทดสอบกับโทรศัพท์จริง (POCO 25078PC3EG) ทั้งลงทะเบียนตรงและผ่านการเปิด Agent; T07 ผ่าน; UI โทรศัพท์ |
| FR-16 | P0 | expected_account ตรวจก่อนโพสต์, ไม่ตรง → พัก | agent/tiktok | test_account_mismatch (mock), T15 + real device | G5-03 | P5 | WIP — อ่านบัญชี (@handle) จาก Profile ก่อนโพสต์บนเครื่องจริง (ทำแบบ manual ใน P1); auto-match + NEEDS_ACTION = P5 |
| FR-17 | P0 | ดาวน์โหลด, hash, push, gallery, กรอกไทย | agent/transfer, agent/tiktok | test_hash_check, T16 + real device | G1-03, G5-02 | P1/P5 | WIP — post runner บนโทรศัพท์จริง (POCO, dry-run): ดาวน์โหลด + ตรวจ SHA-256, push_verified, Gallery, ลบไฟล์ทดสอบ (`test_real_device_post.py`); กรอกข้อความไทย/UI TikTok = P5.4 |
| FR-18 | P0 | Attempt, UNKNOWN, ไม่ retry หลัง submit | api/attempts, agent | test_attempt_state_machine, T17, T18, T19 | G1-04, G5-04 | P1/P5 | WIP — UNKNOWN ไม่ส่งซ้ำ, ปิดเรื่องโดยคนพร้อมหลักฐาน 3 ทาง (E-43, `test_resolution.py`), สำเร็จต้องมีหลักฐาน; retry เฉพาะปัญหาการทำงานหลังแก้; Agent journal recover (P1) |
| FR-19 | P0 | Pause/Cancel ตามขั้น | api/schedules, api/jobs | test_cancel_phase_aware, T14 | G4-04 | P4 | WIP — หยุด/ทำต่อ series (Resume แสดงตัวอย่างจาก Server ก่อนยืนยัน ไม่ยิงรวด), ยกเลิก/แก้เวลารายการที่ยังไม่เริ่ม; เริ่มแล้วยกเลิก/แก้ไม่ได้และติดตามผลต่อ (`test_schedule_changes.py`) |
| FR-20 | P0 | Monthly billing จาก server transaction | api/billing | test_subscription_boundaries, T22 | G6-02, G6-04 | P6 | — |
| FR-21 | P0 | Quota ledger atomic, idempotent | api/ledger | test_ledger_concurrent_reserve (T21), test_refund_once (T10) | G3-04, G6-03 | P3/P6 | WIP — `quota.py`: reserve/settle/release หน่วยคลิป, idempotency key ทุก entry, ล็อก subscription (T10, T21 ผ่าน); แพ็กเกจ Demo 30/เดือน; billing จริง = P6 |
| FR-22 | P0 | Admin/Audit พร้อมเหตุผล before/after | api/admin, web/admin | test_admin_audit, test_admin_permission | G6-05 | P6 | — |
| FR-23 | P0 | Alert/Support อ้าง Job ID | api/notifications, web/notifications | test_notifications | G7-04 | P6/P7 | — |
| FR-25 | P0 (PO add, Q-23) | ประหยัดพลังงานโทรศัพท์: เปิด Wi-Fi ก่อนงาน, ปิดแอป+Wi-Fi หลังผลยืนยัน | agent/power.py, agent/adb.py | tests/unit/test_power.py (12 tests), real-device runs A/B | G5-02 | P1/P5 | WIP — ทำงานบนเครื่องจริง (dry-run); ต่อกับ flow โพสต์จริงใน P5 |
| FR-24 | P1 | Team/Premium (หลัง MVP) | — | — | — | Post-MVP | Out of MVP |

## Non-functional requirements

| ID | Requirement | Module(s) | Planned evidence | Gate | Phase | Impl |
|---|---|---|---|---|---|---|
| NF-01 | Tenant isolation | api (repository layer), media access | cross-tenant suite ทุก resource + media (T01) | G2-01, G7-03 | P2→P7 | WIP — `tenancy.py` (scoped/get_owned), cross-tenant tests ของ Environments (404 แยกไม่ออกจากไม่มีจริง), meta test: ทุกตารางลูกค้ามี `workspace_id` NOT NULL |
| NF-02 | Credential protection | api/agent_tokens, logging, agent/credentials | token entropy test, log/URL scan | G2-02 | P2 | WIP — รหัสผ่านไม่อยู่ในระบบเรา (Supabase); API ถือแค่ public key; access token รับเฉพาะ header และไม่ลง log (test); Agent token = P2.4 |
| NF-03 | URL/file safety, SSRF, resource limits | worker/source, worker sandbox | test_ssrf_redirect (T08), resource limit test | G3-01 | P3 | WIP — allowlist (Server + Agent), `netguard.public_only()` ตรวจทุก resolve รวม redirect ระหว่างดาวน์โหลด (T08 ผ่านด้วย yt-dlp จริง), URL ของ ffmpeg ตรวจก่อน, ต้นฉบับ ≤4 ชม./ไฟล์ ≤8 GB/คลิป ≤512 MB, render thread ≤ ครึ่ง CPU + priority ต่ำ + timeout (`render.RenderLimits`); เหลือ: redirect ภายใน ffmpeg (E-38) |
| NF-04 | P95 < 1s CRUD @50 users | api | load test report | G7-04 | P7 | WIP — dispatch load test (150 เครื่อง/300 โพสต์): claim request p95 77 ms, 100% ภายใน 60 วินาที (E-41); load test CRUD @50 users = P7 |
| NF-05 | Dispatch 95% ≤ 60s | scheduler | load test | G4-05 | P4 | — |
| NF-06 | Retention/lifecycle, ไม่ลบไฟล์ที่ใช้อยู่ | worker/retention | test_retention_active_job (T23) | G6-05 | P6 | — |
| NF-07 | Backup/restore RPO ≤24h RTO ≤4h | ops | restore drill (T24) | G8-02 | P8 | — |
| NF-08 | Observability: ID ใน log/metrics, alerts | all services | log correlation test, alert config | G8-01 | P2→P8 | WIP — `X-Request-ID` ทุก response, `request_id` ใน error body/audit event/log line (method, path, status เท่านั้น) |
| NF-09 | Accessibility/responsive/Thai 360px, zoom 200% | web | browser checks + screenshots | G7-04 | P2→P7 | — |
| NF-10 | Agent update ตรวจ integrity, ไม่ update ระหว่าง Submit, rollback | agent/updater | installer/update tests | G5-01 | P5 | — |

## P0 deliverables traceability

| P0 item | Deliverable | Gate check |
|---|---|---|
| P0.1 | docs/progress.md §Repository assessment | G0-05 (ส่วน) |
| P0.2 | ไฟล์นี้ | G0-01 (ส่วน) |
| P0.3 | docs/gates/G0.md … G8.md | ทุก Gate |
| P0.4 | docs/ui-map.md | G0-02 |
| P0.5 | docs/decisions.md | G0-04 |
| P0.6 | docs/backlog.md (รวม resource/fixture/device plan) | G0-05 |
| — | docs/architecture.md (identity model) | G0-03 |
