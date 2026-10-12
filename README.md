# ClipFlow (punpun)

บริการสมาชิกรายเดือนสำหรับ SME, ครีเอเตอร์ และเอเจนซี: รับลิงก์ YouTube/Bilibili หรือไฟล์วิดีโอที่ผู้ใช้มีสิทธิ์ → ตัดเป็นคลิปแนวตั้ง 9:16 (3–5 นาที) พร้อมชื่อ ซับ และ Caption/Hashtag ที่แก้ได้ → ตรวจและอนุมัติบนเว็บ → ตั้งเวลาโพสต์ทุก X ชั่วโมงไปยังโทรศัพท์ Android ผ่าน **Agent บน Windows ของลูกค้าเอง**

## สถานะ (2026-10-10)

| Gate | ผล | หมายเหตุ |
|---|---|---|
| G0, G3, G4, G5 | **Yes** | ลงนามแล้ว |
| G2 | **Yes** | staging บน Render: https://punpun.tomatoparadise.online |
| G1 | **Yes** | ลงนาม 2026-10-10; ต้นทุนใน `docs/cost-model.md` |
| G6 | **Yes** | ลงนาม 2026-10-10; Stripe โหมดทดสอบใช้ได้บน staging; รับเงินจริงต้องมี production + live key ก่อน |
| G7 | No (0/5) | P7 เริ่มแล้ว: regression T01–T25 บนเครื่อง; ยังไม่มีผู้ใช้ Pilot (D07) |

- **โพสต์จริงยังปิดอยู่:** ระบบหยุดก่อนกดโพสต์ทุกครั้ง (dry-run) โพสต์จริงทำได้เฉพาะเมื่อ PO ให้สิทธิ์ทีละครั้งและบันทึกไว้
- **Agent ล่าสุด:** 0.3.2 (adb ในตัว, หน้าต่างตั้งค่า, รหัสเชื่อมต่อ, ลบไฟล์หลังโพสต์)
- **สถานะล่าสุดและงานถัดไป:** `docs/progress.md`

## สถาปัตยกรรมโดยย่อ

```
เว็บ (React) ──► API (FastAPI) ──► PostgreSQL (ledger โควตา, ตารางโพสต์)
                     ▲
                     │ HTTPS ขาออกเท่านั้น (polling)
               Agent บน Windows ของลูกค้า ──► ADB/USB ──► โทรศัพท์ Android (TikTok)
```

- **ตัดคลิปบนเครื่องลูกค้า:** Agent ดาวน์โหลดหรืออ่านไฟล์ของลูกค้า แล้ววิเคราะห์ ตัด และ render บน PC ของลูกค้าเอง
- **เก็บคลิปในโฟลเดอร์ที่เลือก (Q-33):** ส่งให้ server แค่ SHA-256, ผลตรวจไฟล์ และภาพนิ่ง 3 ช่วง **ไม่อัปโหลดวิดีโอ**
- **โพสต์จากไฟล์เดิม:** ตอนโพสต์ Agent ส่งไฟล์เดียวกันเข้าโทรศัพท์ และตรวจ hash บนเครื่อง
- **ลบไฟล์หลังโพสต์ได้ (Q-34):** ตั้งได้ตอนสร้างงาน
- **โควตาเป็นหน่วยจำนวนเต็ม:** จอง → หักจริงหรือคืน มี idempotency key กันหักซ้ำ
- **โพสต์ที่ไม่ทราบผลไม่ลองซ้ำเอง:** โพสต์ที่หายไปหลังกด Submit จะเป็น UNKNOWN และต้องตรวจยืนยันโดยคน

รายละเอียด: `docs/architecture.md`

## โครงสร้าง repo

| โฟลเดอร์ | เนื้อหา |
|---|---|
| `apps/web/` | เว็บ React + TypeScript + Vite (หน้าภาษาไทย, ธีมมืด/สว่าง, landing page) และ Playwright E2E ใน `e2e/` |
| `services/api/` | API FastAPI + SQLAlchemy + Alembic (migrations 0001–0014) และ integration tests |
| `services/worker/` | pipeline สื่อ: yt-dlp (allowlist + SSRF guard), ตัดตามช่วงเงียบ, render 9:16 ด้วย FFmpeg/libass, ตรวจไฟล์ |
| `agent/` | Windows Agent: ADB, journal การโพสต์, job/post runner, ตัวติดตั้ง, หน้าต่างตั้งค่า, adb ในตัว (`licenses/`, `assets/`) |
| `tools/` | `build_agent.py` (แพ็ก Agent + setup), `check_gate.py`, `staging_rehearsal.py` |
| `docs/` | progress, architecture, decisions, requirements-map, ui-map, backlog, compatibility, `gates/G0–G8.md`, `runbooks/`, `uat/` |
| `logo/` | โลโก้ต้นฉบับ |
| `Dockerfile`, `render.yaml`, `deploy/` | image เดียวสำหรับ staging (API เสิร์ฟเว็บ) และ Render Blueprint |

## เริ่มพัฒนาบนเครื่อง (Windows)

ต้องมี Python 3.14, Node 24, Docker Desktop, FFmpeg (winget) และ Android platform-tools ถ้าจะต่อโทรศัพท์จากโค้ด

บน Windows ไม่มี `make` ให้ใช้ `py tasks.py <target>` แทน

```bash
py tasks.py setup
```

```bash
docker compose up -d
```

```bash
npx supabase start -x studio,storage-api,imgproxy,realtime,edge-runtime,logflare,vector,supavisor,postgres-meta
```

```bash
py tasks.py migrate
```

- `setup` สร้าง `.venv` และติดตั้ง worker กับ api
- `docker compose up -d` เปิด Postgres 16, Redis 7 และ MinIO (bind 127.0.0.1)
- `npx supabase start …` เปิด Auth และ Mailpit บนเครื่อง (ใช้ทดสอบเท่านั้น)
- `migrate` สร้างตารางให้ล่าสุด

เปิด API และเว็บ (ค่า Supabase ของเว็บอยู่ใน `apps/web/.env*.local` ซึ่งไม่ถูก commit):

```bash
.venv/Scripts/python -m uvicorn clipflow_api.app:app --port 8000
```

```bash
cd apps/web && npm run dev
```

## ทดสอบ

```bash
py tasks.py test-unit
```

```bash
py tasks.py test-integration
```

```bash
py tasks.py test-e2e
```

```bash
py tasks.py lint
```

```bash
py tasks.py typecheck
```

```bash
py tasks.py check-gate 7
```

- `test-unit` รัน `tests/unit` และ `services/worker/tests`
- `test-integration` รัน `services/api/tests` บนฐานข้อมูลชั่วคราว ถ้า Postgres ไม่ทำงานจะข้าม แต่การข้ามไม่นับเป็นหลักฐาน
- `test-e2e` รัน Playwright (Edge) กับ Supabase บนเครื่องเท่านั้น
- `lint` รัน ruff กับ oxlint, `typecheck` รัน tsc
- `check-gate` ตรวจ gate record: 0 = ผ่าน, 1 = ยังไม่ผ่าน, 2 = record ไม่ถูกต้อง

CI (`.github/workflows/ci.yml`) รัน lint, unit, integration, E2E, web build และ smoke ของ staging image

เทสต์ที่ต้องใช้ของจริงต้องเปิดเองด้วย env เช่น `CLIPFLOW_REAL_DEVICE=1` (โทรศัพท์ทาง USB), `CLIPFLOW_REAL_SOURCE_URL=…` (ดาวน์โหลดจริง) และ `CLIPFLOW_AGENT_BUNDLE=1` (exe ที่แพ็กแล้ว) ดูคำสั่งครบใน `CLAUDE.md`

## Windows Agent

**Build:**

```bash
.venv/Scripts/python tools/build_agent.py
```

ได้ไฟล์ใน `var/dist/` (ไม่ถูก commit):
- `punpun-agent-<v>.zip` และ `.sha256`: bundle สำหรับอัปเดต
- **`punpun-agent-setup-<v>.exe`**: ไฟล์เดียวที่ลูกค้าดับเบิลคลิก ไม่ต้องมี Python และไม่ต้องใช้สิทธิ์ admin

**สิ่งที่ setup ทำให้ลูกค้า:**
1. ติดตั้งหรืออัปเดต Agent โดยตรวจ SHA-256 และ manifest ทุกไฟล์
2. เพิ่มคำสั่ง `punpun-agent` ใน PATH
3. สร้าง shortcut "punpun Agent" และ "ตั้งค่า punpun Agent"
4. เปิด**หน้าต่างตั้งค่า** ให้ลูกค้า:
   - ใส่**รหัสเชื่อมต่อ** 8 ตัวจากหน้า Agent บนเว็บ ไม่ต้องคัดลอก token
   - เลือกโฟลเดอร์เก็บคลิป และโฟลเดอร์วิดีโอของตัวเอง
   - เลือกได้ว่าจะให้ Agent เริ่มเองตอนเปิดเครื่องหรือไม่

**คำสั่งที่ใช้บ่อย** (รันจาก source ด้วย `.venv/Scripts/python -m agent …`, เวอร์ชันที่ติดตั้งแล้วใช้ `punpun-agent …`):

| คำสั่ง | ทำอะไร |
|---|---|
| `settings` | เปิดหน้าต่างตั้งค่า |
| `pair --server S --code XXXX-XXXX` | เชื่อมเครื่องด้วยรหัสเชื่อมต่อ |
| `connect` | เริ่มทำงาน: รับงานตัดคลิป และโพสต์ตามตาราง (dry-run) |
| `status` / `doctor --serial S` | ดูสถานะ Agent, โทรศัพท์, adb และพอร์ต 5037 |
| `set-folder D:\punpun\clips --move` | เปลี่ยนโฟลเดอร์คลิปและย้ายคลิปเดิมตาม |
| `install --bundle B --sha256 H` / `rollback` | อัปเดตหรือย้อนเวอร์ชัน (ไม่ทำระหว่างมีโพสต์ที่รอผล) |
| `licenses` | ดูสัญญาอนุญาตของซอฟต์แวร์บุคคลที่สาม (adb) |

**ข้อจำกัดตอนนี้:**
- Agent ไม่รับงานใหม่ถ้าโฟลเดอร์คลิปเหลือที่ว่างไม่ถึง 5 GB
- exe ยังไม่ได้ sign จึงมีคำเตือน SmartScreen
- adb ที่แถมมาต้องตรวจเงื่อนไขอนุญาตก่อนแจกผู้ใช้ภายนอก (E-51)

## Staging

- **ระบบ:** Render (Singapore) + Supabase project `punpun`, image เดียวที่ API เสิร์ฟเว็บด้วย
- **ฐานข้อมูล:** ตารางอยู่ใน schema `clipflow` ไม่ใช่ `public`
- **Deploy:** deploy master เมื่อ CI ผ่าน migration แบบเพิ่มอย่างเดียว ถ้าต้องย้อนให้ deploy image ก่อนหน้า
- **ซ้อมบนเครื่อง:**

  ```bash
  .venv/Scripts/python tools/staging_rehearsal.py
  ```

- **คู่มือ:** `docs/runbooks/staging.md` และ `docs/runbooks/supabase-auth.md`

## กติกาความปลอดภัย

- **ไม่มีคำสั่งโพสต์จริงที่เปิดได้ด้วยไฟล์ env:** ค่าเริ่มต้นคือ `POSTING_MODE=dry_run` และ `BILLING_PROVIDER=sandbox` (ดู `.env.example`)
- **ไม่เก็บ credential ใน source, log, URL หรือรายงาน:**
  - token ของ Agent เก็บบน server เป็น prefix + SHA-256 และแสดงครั้งเดียว
  - บนเครื่องลูกค้าเข้ารหัสด้วย DPAPI
- **แยกข้อมูลตาม workspace:** ทุกแถวมี `workspace_id` และ server ตรวจความเป็นเจ้าของทุกครั้ง ถ้าข้าม tenant จะได้ 404 เหมือนไม่มีข้อมูล
- **เคารพข้อจำกัดของแพลตฟอร์มต้นทาง:** ถ้าโดน bot check จะพักตาม cool-down ไม่หมุน IP หรือใช้ proxy และไม่ลบลายน้ำ
- **ไฟล์ที่สร้างขึ้นและหลักฐานทดสอบอยู่ใน `var/`:** ไม่ถูก commit

## เอกสาร

| ไฟล์ | เนื้อหา |
|---|---|
| `PRD_CLAUDE_CODE.md` | PRD และสัญญาการพัฒนา (แหล่งอ้างอิงหลัก) |
| `CLAUDE.md` | แนวทางและคำสั่งทั้งหมดสำหรับการพัฒนา |
| `docs/progress.md` | สถานะล่าสุดและงานถัดไป (อ่านก่อนเริ่มงาน) |
| `docs/architecture.md` | Components, identity/permission model, state machines |
| `docs/decisions.md` | D01–D07, คำตอบของ PO (Q-xx), engineering decisions (E-xx) |
| `docs/requirements-map.md` | FR/NF → module → test → gate |
| `docs/ui-map.md` | Routes, journeys และสถานะของทุกหน้าจอ |
| `docs/backlog.md` | Backlog ตาม Phase |
| `docs/compatibility.md` | เครื่องมือและอุปกรณ์ที่ทดสอบแล้ว (QA: POCO 25078PC3EG) |
| `docs/gates/G0.md … G8.md` | Gate records (47 checks) |
| `docs/uat/` | UAT P7 (T01–T25) และรายงาน QA |
