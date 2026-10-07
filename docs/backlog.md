# Backlog (prioritized) + resource / fixture / device plan

ลำดับตามเส้นทางวิกฤต PRD §O.10: POC → Tenant/Agent identity → Video → Scheduler → Posting verification → Billing → UAT → Launch
ประมาณการเป็น "วันทำงานของนักพัฒนา 1 คน" (ไม่ใช่สัญญา) — ทบทวนหลัง P1 ตาม PRD

## P0 — Scope & baseline (ทำในเซสชันนี้)
| # | งาน | สถานะ |
|---|---|---|
| P0.1 | Repository assessment | Done — docs/progress.md |
| P0.2 | Requirements map | Done — docs/requirements-map.md |
| P0.3 | Gate records G0–G8 + `check-gate` | Done — docs/gates/, tools/check_gate.py |
| P0.4 | UI route/state map | Done — docs/ui-map.md |
| P0.5 | Decision register | Done — docs/decisions.md (D01–D07 Open, Q-01..Q-11 รอ PO) |
| P0.6 | Backlog + resource/fixture/device plan | Done — ไฟล์นี้ |
| — | รอ PO: sign-off G0-01..05 และตอบ Q-01..Q-10 | **Blocked on PO** |

## P1 — Feasibility POC (PO อนุญาตให้ทำคู่ขนาน 2026-10-06) — สถานะ 2026-10-07
| # | งาน | ต้องการจากภายนอก | ประมาณ |
|---|---|---|---|
| P1.1 | Done (logic + 5 real links) — `poc inspect`, error classes, limits, SSRF guard | — | 2 |
| P1.2 | Partial — 5/10 links (YT 2, Bili 3) ใน docs/compatibility.md | ลิงก์เพิ่ม YT ≥3, Bili ≥2 | 1 |
| P1.3 | Done (pending human playback QA) — 15 คลิป tpl v1 + 4 คลิป tpl v2 | ฟอนต์ Noto Sans Thai ก่อน P3 | 3 |
| P1.4 | Partial — ADB adapter + dry-run CLI (fake-runner tests); Thai input ยังไม่เริ่ม | โทรศัพท์ 2 รุ่น + อนุญาตติดตั้ง helper app สำหรับพิมพ์ไทย | 3 |
| P1.5 | Authorized posting + verification บน ≥2 รุ่น | บัญชี TikTok ทดสอบที่ได้รับอนุญาต + D04 | 3 |
| P1.6 | Partial — journal + recovery (fault-injection unit tests) | ทดสอบตัดการเชื่อมต่อบนเครื่องจริง | 2 |
| P1.7 | Terms review (dated) + compatibility matrix + benchmark/cost | PO อ่านและตัดสิน D04 | 2 |

## P2 — SaaS foundation (ขึ้นกับ G1 Yes — เริ่มตาม PO override Q-22)
สถานะ 2026-10-07: ✅ FastAPI skeleton + Alembic • ✅ Auth/Workspace + reset (backend) • ✅ Tenant repository layer + cross-tenant tests (Environments) — ที่เหลือด้านล่าง
Docker Compose (Postgres/Redis/MinIO) • FastAPI skeleton + Alembic • Auth/Workspace + reset • Tenant repository layer + cross-tenant test suite • Environment + plan caps (transactional) • Token lifecycle + log redaction • Agent authenticate/heartbeat/fencing • Device register/ownership • Web shell (sidebar, auth, dashboard, connection, tokens, environments, agents, devices, settings) • CI (lint/typecheck/test/build) • staging deploy/rollback — ประมาณ 10–12 วัน

## P3 — Video production (ขึ้นกับ G2) — 10 วัน (ปรับตาม Q-15: logic ผลิตคลิปรันบน Agent; Server รับคลิป ตรวจ hash ทำ preview/approve)
Ingest + SSRF guard • transcript adapter • segment selection (seeded) • render worker (Dramatiq) • template versions • metadata generation adapter • quota reserve/settle/refund • Create wizard, Jobs, Job detail + real preview + approve

## P4 — Scheduler (ขึ้นกับ G3) — 5 วัน
schedule_core + PRD examples • preview endpoint • collision/device lock/claim • pause/resume/defer/skip • week/list UI • dispatch load test

## P5 — Agent & publishing (ขึ้นกับ G4) — 10 วัน + 3–4 วันจาก Q-15/Q-17
ตาม Q-15 (ข2): บรรจุโมดูล media ใน Agent (E-18), claim render job, upload คลิป + sha256, cool-down UI; ตาม Q-17: เลือกไฟล์บนเครื่อง Agent เป็นต้นฉบับ

Windows packaging (installer, credential store, local UI) • claim/download/hash/transfer • account verification • TikTok UI state machine • attempt events + UNKNOWN + resolve UI • update/rollback • fault tests on real devices

## P6 — Billing & Admin (ขึ้นกับ G5; prototype ทำก่อนได้) — 5 วัน
## P7 — Pilot/UAT (ขึ้นกับ G6) — 5 วัน + เวลาผู้ทดสอบ
## P8 — Launch readiness (ขึ้นกับ G7) — 5 วัน

## Resource plan (PRD สมมติ 4 บทบาท — ยังไม่มีชื่อผู้รับผิดชอบ)
| บทบาท | ผู้รับผิดชอบ | หน้าที่ใน Gate |
|---|---|---|
| PO | ปิยศักดิ์ สุทธิประภา | อนุมัติ G0, G1, G5, G6, G7, G8 |
| Tech Lead | ปิยศักดิ์ สุทธิประภา (Q-20) | G1, G2 |
| QA | ปิยศักดิ์ สุทธิประภา (Q-20) | G2–G7 |
| Video/Agent Lead | ปิยศักดิ์ สุทธิประภา (Q-20) | G3, G5 |
| Ops/Finance | ปิยศักดิ์ สุทธิประภา (Q-20) | G6–G8 |
งบ POC: **ยังไม่ระบุ** (ค่า AI/ASR, เครื่อง Android 2 รุ่น, storage)

## Authorized fixture plan
| Fixture | แหล่ง | สถานะ |
|---|---|---|
| วิดีโอสังเคราะห์สำหรับ unit/render test | สร้างด้วย ffmpeg `testsrc`/`sine` ภายในเทส (ไม่ commit ไฟล์ใหญ่) | พร้อมทำใน P1 |
| ฟอนต์ไทย | POC ใช้ Leelawadee UI (ระบบ, ห้ามแจกจ่าย); P3 ใช้ Noto Sans Thai (SIL OFL) | E-13 |
| ลิงก์ YouTube ≥5 / Bilibili ≥5 ที่ผู้ใช้มีสิทธิ์ | PO ส่ง 2026-10-06 (YT 2, Bili 3) | **บางส่วน** — ขาด YT 3, Bili 2 |
| ข้อความ transcript ไทย/จีน/อังกฤษตัวอย่าง | สร้างเอง | พร้อมทำ |

## Device plan
| รายการ | ต้องการ | สถานะ |
|---|---|---|
| Android รุ่นที่ 1, 2 (ต่างผู้ผลิต/เวอร์ชัน Android) | USB debugging, ติดตั้ง TikTok | **ยังไม่มี** — `adb devices` ไม่พบเครื่อง (2026-10-06) |
| บัญชี TikTok ทดสอบ | PO แจ้งว่า login อยู่ในโทรศัพท์แล้ว (2026-10-06) | มี (ยังตรวจไม่ได้เพราะโทรศัพท์ยังไม่เชื่อม ADB) |
| Windows baseline | Windows 11 Pro 10.0.26100 (เครื่องนี้) | มี |
