# ClipFlow — Architecture & Identity Model (P0 baseline)

สถานะ: Draft P0 สำหรับ Review • อ้างอิง PRD_CLAUDE_CODE.md v1.1 (§E, §F, §G, §H, §O.6, §O.7)
เอกสารนี้เป็นหลักฐานสำหรับ G0-03 และส่วนหนึ่งของ G0-04 ยังไม่ใช่ระบบที่ Implement แล้ว

## 1. Components

```
Browser (apps/web, React/TS, Thai UI)
   │ HTTPS, cookie session (browser auth)
   ▼
API (services/api, FastAPI)  ──►  PostgreSQL (source of truth: tenants, ledger, leases, attempts)
   │                         ──►  Object storage (S3-compatible; local adapter in dev)
   │ enqueue (idempotent by job/clip id)
   ▼
Redis queue ──► Render worker (services/worker: yt-dlp adapter, transcript, FFmpeg)
Scheduler (services/scheduler): DB polling, materializes due ScheduleItems → device queue
   ▲
   │ HTTPS outbound polling only (agent auth: short-lived session token)
Customer Windows Agent (agent/) ──ADB/UIAutomator2──► Android device ──► TikTok app
```

กฎ: Postgres คือความจริงของสถานะ (claim, lease, ledger, attempt) — Redis เป็นเพียงตัวปลุก/คิวงาน Render ที่ทำซ้ำได้อย่างปลอดภัย (ดู E-02 ใน decisions.md)

## 2. Identity & permission model (G0-03)

| Concept | นิยาม | เป็น Credential? | ผู้กำหนด | ขีดจำกัด |
|---|---|---|---|---|
| Workspace | หน่วย Tenant; ทุกแถวที่เป็นของลูกค้ามี `workspace_id` | — | Server | 1 Owner ใน MVP |
| User / Username | ตัวระบุบัญชี (ไม่ใช่ความลับ) ใช้ทั้ง Web login และคู่กับ Agent Token | ไม่ | ผู้ใช้ตอนสมัคร (unique) | — |
| Environment | ขอบเขตการทำงานของ Agent ภายใน Workspace (เช่น "สำนักงาน", "บ้าน") กำหนด `registered_agent_limit` และ `concurrent_session_limit` และ device entitlement | ไม่ | Owner ผ่านเว็บ, Server ตรวจกับ Plan | ผลรวมทุก Environment ≤ Plan cap |
| Agent Token | หลักฐานสิทธิ์ ผูก 1 Environment ฝั่ง Server; เก็บ `token_prefix` (public) + `secret_hash` | **ใช่** | Server generate; แสดงเต็มครั้งเดียว | Expiry, Revoke, Rotate |
| Agent Installation | การติดตั้งหนึ่งครั้ง ระบุด้วย `installation_id` ที่ Agent สร้างครั้งแรกและเก็บในเครื่อง — เป็นตัวระบุ ไม่ใช่หลักฐานว่าเป็นเครื่องจริง | ไม่ | Agent | นับกับ `registered_agent_limit` |
| Agent Session | Session อายุสั้นที่ได้จาก `/agent/authenticate`; มี `generation` (fencing) | ใช่ (short-lived) | Server | นับกับ `concurrent_session_limit`; 1 Active session ต่อ Installation |
| Device | โทรศัพท์ Android ระบุด้วย `adb_serial` (normalize) ภายใน Environment | **ไม่** (Serial ไม่ใช่หลักฐานความเป็นเจ้าของ) | ลงทะเบียนผ่าน Agent, Server ตรวจ Owner/cap | Plan device cap |
| Expected account | บัญชี TikTok ที่เครื่องนี้ต้องโพสต์ (`expected_account`) | ไม่ | Owner | Agent ตรวจบัญชีจริงก่อน Submit ทุกครั้ง |

### 2.1 Authentication flows

- **Browser**: email/username + password → HttpOnly secure session cookie; CSRF protection; password reset ใช้ token ใช้ครั้งเดียวที่หมดอายุ และตอบเหมือนกันไม่ว่าบัญชีมีอยู่หรือไม่ (FR-01)
- **Agent**: `POST /v1/agent/authenticate {username, token, installation_id, agent_version}` (secret อยู่ใน body/header ไม่อยู่ใน query string)
  1. ค้น Token ด้วย prefix → เปรียบเทียบ hash แบบ constant-time → ตรวจ expiry/revoked
  2. Username ต้องเป็นเจ้าของ Token; ถ้าไม่ตรง ตอบ error ทั่วไปเหมือน token ผิด (ไม่เปิดเผยเจ้าของ — T02)
  3. Environment มาจาก Token ฝั่ง Server เท่านั้น; ฟิลด์ environment ที่ Client ส่งมาถูกละเลย (T05)
  4. `installation_id` เดิม → ใช้ทะเบียนเดิม (T03); ใหม่ → ตรวจ `registered_agent_limit` แบบ transactional
  5. ออก Session ใหม่ด้วย `generation = previous + 1` และทำให้ Session เดิมของ Installation เดียวกันหมดสิทธิ์ (fencing — T04); ตรวจ `concurrent_session_limit`
- Agent token **ไม่มีสิทธิ์** เรียก Web API ใด ๆ; Web session ไม่มีสิทธิ์เรียก Agent claim API

### 2.2 Authorization rules

1. ทุก Query ของ Resource ลูกค้าใส่เงื่อนไข `workspace_id = current_workspace` ใน Repository layer (ไม่ใช่เฉพาะใน Route) และตรวจ Foreign resource ให้อยู่ Tenant เดียวกัน (เช่น ScheduleItem → Device, Clip ต้อง Workspace เดียวกัน)
2. ไฟล์มีเดียเข้าถึงผ่าน `/clips/{id}/media` ที่ตรวจสิทธิ์แล้วออก URL อายุสั้น — ไม่มี Public bucket URL
3. Agent เห็นเฉพาะ Job/Device ใน Environment ของ Session และเฉพาะ Device ที่ Lease ของตน
4. Platform Admin / Support ใช้ Role แยก; ทุกการอ่าน/แก้ข้อมูลลูกค้าบันทึก AuditEvent; Support ไม่เห็น Token/secret
5. คำตอบที่ปฏิเสธสิทธิ์ข้าม Tenant ใช้ 404 (ไม่ยืนยันการมีอยู่ของ Resource)

### 2.3 Heartbeat / session (ค่าเสนอ ต้องปรับหลังทดสอบเครือข่ายจริง)

Heartbeat 15 วินาที • stale เมื่อขาด 60 วินาที • หมดอายุ 90 วินาที • Revoke Token → Session ที่เกี่ยวข้องหมดสิทธิ์ ≤ 60 วินาที (ตรวจทุก request ของ Agent จึงมีผลทันทีในทางปฏิบัติ)

### 2.4 Device registration

`POST /v1/agent/devices/register {serial, model, android_version}` → normalize serial (trim, case-preserving แต่เปรียบเทียบแบบ case-insensitive) →
- ไม่มี Binding: สร้าง Device ใน Environment ของ Session ถ้าไม่เกิน device cap ของ Plan (transactional)
- มี Binding ของ Workspace เดียวกัน/Environment เดียวกัน: idempotent
- มี Binding ของ Workspace อื่นหรือ Environment อื่น: ปฏิเสธ `DEVICE_OWNERSHIP_CONFLICT` — ไม่ย้ายอัตโนมัติ (T07); การโอนต้องให้เจ้าของเดิม Unbind หรือ Support resolution ที่ตรวจสิทธิ์และ Audit

## 3. State machines

### 3.1 Job
```
RECEIVED → SOURCE_VALIDATED → DOWNLOADING → ANALYZING → RENDERING → READY_FOR_REVIEW → APPROVED → SCHEDULED
   └──────────────┴───────────────┴─────────────┴────────────┴──→ NEEDS_ACTION | FAILED | CANCELLED
```
Quota: reserve ก่อนเริ่ม DOWNLOADING (หรือก่อน RENDERING ตาม E-04) → settle เมื่อ Render สำเร็จต่อคลิป → refund ส่วนที่ไม่ได้ใช้ เมื่อ FAILED/CANCELLED/ได้คลิปน้อยกว่าที่กัน (ledger idempotency key = `job:{id}:{event}`)

### 3.2 Publish attempt
```
SCHEDULED → CLAIMED → TRANSFERRING → PREPARING → SUBMITTING → VERIFYING → VERIFIED_SUCCESS
                │            │             │            │            │
                └────────────┴─────────────┴→ RETRYABLE_FAILED (เฉพาะก่อน SUBMITTING)
                                                        └────────────┴→ UNKNOWN (ห้าม Retry อัตโนมัติ)
อื่น ๆ: NEEDS_ACTION (ผิดบัญชี/Login wall/CAPTCHA/UI ไม่รู้จัก), SKIPPED, CANCELLED (เฉพาะก่อน SUBMITTING)
```
- ทุก Event จาก Agent มี `event_id` (dedupe), `attempt_id`, `lease_generation`, `state_version`; Server ปฏิเสธ Event จาก generation เก่า
- Lease หมดอายุ **ก่อน** SUBMITTING → RETRYABLE_FAILED หลังยืนยันว่าไม่มี Submission (T17)
- Lease หมดอายุ **ที่/หลัง** SUBMITTING → UNKNOWN, Series ของเครื่องนั้นถูกพักจนมีการ Resolve (T18)
- Resolve UNKNOWN (`/publish-attempts/{id}/resolve`) ต้องมีหลักฐานและผู้ตัดสิน: พบโพสต์ → VERIFIED_SUCCESS; ยืนยันว่าไม่ได้โพสต์ → RETRYABLE_FAILED; ยังไม่รู้ → คง UNKNOWN UI ห้าม preselect ตัวเลือก Retry

### 3.3 Subscription
`PENDING_PAYMENT → ACTIVE → (GRACE?) → EXPIRED`; สิทธิ์เปลี่ยนจาก Webhook ที่ตรวจลายเซ็นแล้วเท่านั้น (FR-20); นโยบาย Grace เป็น D05/D06

## 4. Scheduling (สรุปจาก PRD §G — รายละเอียดการตัดสินใจใน decisions.md E-05..E-08)

`slot[0] = normalize(start)`; `slot[i] = normalize(slot[i-1] + X h)` โดย `normalize(t)` = t ถ้าเวลาท้องถิ่นอยู่ใน `[window_start, window_end)` มิฉะนั้นเลื่อนไป `window_start` ของวันถัดไปที่อนุญาต; คำนวณใน IANA timezone แล้วเก็บ UTC
ตัวอย่างที่ต้องผ่าน (Asia/Bangkok): 09:00, N=6, X=2, 09–21 → 09,11,13,15,17,19; 19:00, N=3 → 19:00, 09:00(+1), 11:00(+1)

## 5. Data ownership & storage

- Media keys: `ws/{workspace_id}/jobs/{job_id}/...` — แต่ไม่ใช้ key เป็นการตรวจสิทธิ์; สิทธิ์ตรวจใน DB เสมอ
- Credential: Server เก็บเฉพาะ hash; Agent เก็บ Token ใน Windows Credential Manager (DPAPI) — ไม่เขียนลง config/plain log
- Log redaction: middleware ตัด header `Authorization`, ฟิลด์ `token`, `password`, `secret` และ URL query ทั้งหมดของ endpoint auth
