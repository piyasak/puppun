# Requirements map (FR / NF → module → test → gate)

สถานะ Impl: `—` ยังไม่เริ่ม • `WIP` • `Done (logic)` ผ่าน unit/integration แต่ยังไม่มีหลักฐาน live • `Done (live)` มีหลักฐานจริงตาม Gate
คอลัมน์ Test เป็นชื่อชุดทดสอบที่ **วางแผน** ไว้ (ยังไม่มีไฟล์จนกว่าจะระบุ path)

## Functional requirements

| ID | Pri | Requirement (ย่อ) | Module(s) | Planned tests / UAT | Gate | Phase | Impl |
|---|---|---|---|---|---|---|---|
| FR-01 | P0 | สมาชิก/Workspace, reset ไม่เปิดเผยบัญชี | Supabase Auth (E-27), api/identity, api/onboarding, web/auth | test_auth, test_tenant_isolation, test_supabase_live, T01 | G2-01 | P2 | WIP — สมัคร/เข้า/reset = Supabase Auth; API ตรวจ JWT ด้วย JWKS + `/v1/onboarding` (Workspace + rights Q-14) + `/v1/me`; tests ผ่าน; หน้าเว็บ auth (`apps/web`) + Playwright E2E บน Supabase local 2/2 ผ่าน; ทดสอบ cloud ด้วยอีเมลจริง (PO) และ Custom SMTP ยังไม่มี |
| FR-02 | P0 | รับลิงก์, allowlist, limit, rights declaration | api/jobs, worker/source | test_source_validation, test_ssrf, T08 | G1-01, G3-01 | P1/P3 | WIP — ลิงก์: allowlist/https/no-IP/no-credentials; ไฟล์ของลูกค้า (Q-17): `local_source.py` ตรวจ regular file, ≤8 GB, ffprobe ต้องเจอ video+duration, SHA-256 เป็น source ID, ไม่เก็บ path เต็ม; ทดสอบจริงกับไฟล์ 61 นาที; rights acceptance (Q-14) = P2 |
| FR-03 | P0 | ดาวน์โหลด + metadata, แยกสถานะข้อผิดพลาด, retry จำกัด | worker/source (yt-dlp adapter) | test_source_errors, source compatibility report | G1-01, G3-01 | P1/P3 | WIP — error classes แยก (เพิ่ม SOURCE_RATE_LIMITED, UNSUPPORTED_FILE); bot check → cool-down ต่อแพลตฟอร์ม 1→6 ชม. (`cooldown.py`); range ไม่ครบ → retry 1 ครั้ง; 10/10 real links read |
| FR-04 | P0 | คัดช่วง + random มี seed/template version | worker/analysis | test_segment_selection_reproducible | G3-02 | P3 | WIP — audio-pause boundaries + seeded selection (`segments.py`, E-11); real sources 2026-10-07 |
| FR-05 | P0 | ประเมินจำนวนคลิปได้จริง แจ้งก่อนใช้โควตา | worker/analysis, api/jobs | test_insufficient_content, T09 | G3-04 | P3 | WIP — `Selection.insufficient` reports fewer clips (unit test); UI/quota = P3 |
| FR-06 | P0 | Render MP4 9:16 + เสียง, probe | worker/render | test_render_probe, MP4 samples | G1-02, G3-03 | P1/P3 | WIP — 9:16 MP4 H.264/AAC + ffprobe in manifest (real sources); not yet played on a phone |
| FR-07 | P0 | Title/Ending/Caption/Hashtag/ซับ แก้ไขได้ มี version | worker/text, api/clips, web/job-detail | test_metadata_versioning, Thai glyph review | G1-02, G3-03 | P1/P3 | WIP — Thai Title/Ending burned in, Thai-safe wrap; text from fixed template (Q-02 AI open); editing/versioning = P3 |
| FR-08 | P0 | Review mode / Auto mode | api/clips, scheduler | test_approval_boundary | G3-05 | P3 | — |
| FR-09 | P0 | Schedule ทุก X ชม. จากเวลานัดล่าสุด | scheduler/core | test_schedule_core (PRD examples), T11 | G4-01 | P4 | — |
| FR-10 | P0 | Window [start,end) + IANA tz, เก็บ UTC | scheduler/core | test_schedule_window_boundaries | G4-01 | P4 | — |
| FR-11 | P0 | Offline skip/defer, ไม่ burst, collision | scheduler | test_offline_no_burst, test_collision, T12, T13 | G4-02, G4-03 | P4 | — |
| FR-12 | P0 | Token generate/copy once/expiry/revoke/rotate, hash only | api/agent_tokens, web/connection | test_token_lifecycle, log scan, T02 | G2-02 | P2 | — |
| FR-13 | P0 | Environment: registered_agent_limit แยก concurrent_session_limit, plan cap รวม | api/environments | test_env_limits_concurrent, T05 | G2-03 | P2 | — |
| FR-14 | P0 | installation_id คงที่, reconnect ไม่เพิ่มทะเบียน, fencing | api/agent_auth, agent/identity | test_reconnect_20x (T03), test_duplicate_session (T04) | G2-03, G5-06 | P2/P5 | — |
| FR-15 | P0 | Serial registration ผ่าน Agent, ownership conflict | api/devices, agent/adb | test_device_ownership, T07 | G2-04 | P2 | WIP — `agent/adb.py` device states + serial normalization (fake-runner tests); no real device yet |
| FR-16 | P0 | expected_account ตรวจก่อนโพสต์, ไม่ตรง → พัก | agent/tiktok | test_account_mismatch (mock), T15 + real device | G5-03 | P5 | WIP — อ่านบัญชี (@handle) จาก Profile ก่อนโพสต์บนเครื่องจริง (ทำแบบ manual ใน P1); auto-match + NEEDS_ACTION = P5 |
| FR-17 | P0 | ดาวน์โหลด, hash, push, gallery, กรอกไทย | agent/transfer, agent/tiktok | test_hash_check, T16 + real device | G1-03, G5-02 | P1/P5 | WIP — เครื่องจริง: staging push + SHA-256 + Gallery + share intent ด้วย MediaStore URI + แคปชันไทย/emoji ผ่าน ADBKeyboard (runbook) |
| FR-18 | P0 | Attempt, UNKNOWN, ไม่ retry หลัง submit | api/attempts, agent | test_attempt_state_machine, T17, T18, T19 | G1-04, G5-04 | P1/P5 | WIP — เครื่องจริง: crash หลังกดโพสต์ → UNKNOWN, ไม่ retry; resolve ด้วยหลักฐาน → VERIFIED_SUCCESS (runbook); server-side = P2/P5 |
| FR-19 | P0 | Pause/Cancel ตามขั้น | api/schedules, api/jobs | test_cancel_phase_aware, T14 | G4-04 | P4 | — |
| FR-20 | P0 | Monthly billing จาก server transaction | api/billing | test_subscription_boundaries, T22 | G6-02, G6-04 | P6 | — |
| FR-21 | P0 | Quota ledger atomic, idempotent | api/ledger | test_ledger_concurrent_reserve (T21), test_refund_once (T10) | G3-04, G6-03 | P3/P6 | — |
| FR-22 | P0 | Admin/Audit พร้อมเหตุผล before/after | api/admin, web/admin | test_admin_audit, test_admin_permission | G6-05 | P6 | — |
| FR-23 | P0 | Alert/Support อ้าง Job ID | api/notifications, web/notifications | test_notifications | G7-04 | P6/P7 | — |
| FR-25 | P0 (PO add, Q-23) | ประหยัดพลังงานโทรศัพท์: เปิด Wi-Fi ก่อนงาน, ปิดแอป+Wi-Fi หลังผลยืนยัน | agent/power.py, agent/adb.py | tests/unit/test_power.py (12 tests), real-device runs A/B | G5-02 | P1/P5 | WIP — ทำงานบนเครื่องจริง (dry-run); ต่อกับ flow โพสต์จริงใน P5 |
| FR-24 | P1 | Team/Premium (หลัง MVP) | — | — | — | Post-MVP | Out of MVP |

## Non-functional requirements

| ID | Requirement | Module(s) | Planned evidence | Gate | Phase | Impl |
|---|---|---|---|---|---|---|
| NF-01 | Tenant isolation | api (repository layer), media access | cross-tenant suite ทุก resource + media (T01) | G2-01, G7-03 | P2→P7 | WIP — `tenancy.py` (scoped/get_owned), cross-tenant tests ของ Environments (404 แยกไม่ออกจากไม่มีจริง), meta test: ทุกตารางลูกค้ามี `workspace_id` NOT NULL |
| NF-02 | Credential protection | api/agent_tokens, logging, agent/credentials | token entropy test, log/URL scan | G2-02 | P2 | WIP — รหัสผ่านไม่อยู่ในระบบเรา (Supabase); API ถือแค่ public key; access token รับเฉพาะ header และไม่ลง log (test); Agent token = P2.4 |
| NF-03 | URL/file safety, SSRF, resource limits | worker/source, worker sandbox | test_ssrf_redirect (T08), resource limit test | G3-01 | P3 | — |
| NF-04 | P95 < 1s CRUD @50 users | api | load test report | G7-04 | P7 | — |
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
