# Decision register

สถานะที่ใช้: **Open** (ยังไม่ตัดสิน) • **Proposed** (ทีมพัฒนาเสนอ รอผู้มีสิทธิ์ยืนยัน) • **Accepted** (มีผู้อนุมัติจริงบันทึกไว้) • **Superseded**
กฎ: Decision เชิงพาณิชย์/ขอบเขตต้องให้ PO ยืนยัน — Agent ห้ามเปลี่ยนเป็น Accepted เอง; Engineering decision ที่ย้อนกลับได้ใช้ Proposed และดำเนินงานต่อได้ แต่ต้องแจ้งใน Gate review

## 1. Product / commercial decisions (จาก PRD §O.14)

| ID | Decision | Phase ที่ต้องปิด | Owner | Status | ผลกระทบถ้ายังไม่ปิด |
|---|---|---|---|---|---|
| D01 | ชื่อแบรนด์จริง โดเมน และ Owner | P0 | PO | Open | ใช้ชื่อ "ClipFlow" เป็นชื่อทำงานเท่านั้น; G0-01 No |
| D02 | ชนิดลิงก์ที่รองรับ / ความยาวต้นฉบับสูงสุด / จำนวนคลิปสูงสุดต่องาน | P1 | PO + Video Lead | Open — ค่าเสนอใน Q-03 | กำหนด limit ของ Ingest (FR-02, G3-01) ไม่ได้ |
| D03 | Windows / Android / TikTok versions ที่รองรับ | P1 | Agent Lead | Open | G1-03 ทำไม่ได้จนมีเครื่องจริง |
| D04 | รูปแบบช่องทางเผยแพร่ | P1 | PO | **Accepted (PO in chat, 2026-10-06)**: ต้องเลือกได้ทั้ง 2 ช่องทาง (ADB UI automation และ TikTok Content Posting API) — Implement ADB UI automation ก่อน; API เป็นงานถัดไปหลังตรวจข้อกำหนด/App audit ของ TikTok | ยังต้องมี dated terms review สำหรับ G1-05 |
| D05 | ราคาจริง โควตา จำนวนเครื่อง/Agent/Session ต่อแพ็กเกจ กำไรขั้นต้นเป้าหมาย | P6 | PO + Finance | Open | ใช้ Plan ทดสอบที่ระบุว่า Demo เท่านั้น |
| D06 | ผู้ให้บริการรับชำระ ภาษี เอกสาร Auto-renew Refund | P6 | PO + Finance | Open | Billing ใช้ sandbox adapter เท่านั้น |
| D07 | Pilot users, Support hours, Release cohort | P7/P8 | PO + Ops | Open | — |

## 2. Clarifications ที่พบระหว่างอ่าน PRD (ต้องการคำตอบจาก PO ก่อน G0-04 เป็น Yes)

| ID | ประเด็น | สิ่งที่ PRD ระบุ | ช่องว่าง / ความขัดกัน | ข้อเสนอ (Proposed) | Owner | Status |
|---|---|---|---|---|---|---|
| Q-01 | ภาษาซับไตเติล | FR-07 | ต้นฉบับอาจเป็นจีน/อังกฤษ | **ไม่มีการแปลใน MVP** — ซับใช้ภาษาต้นฉบับ; Title/Ending/Caption/Hashtag เป็นไทย; การแปลซับเป็นงานใน Phase ก่อน Production (backlog) | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-02 | ที่มา Transcript และการเลือกช่วง "AI" | FR-04 "เลือกช่วงแบบ AI หรือสุ่มจากช่วงที่ผ่านการคัดแล้ว" | ไม่ระบุว่า transcript มาจากซับของแพลตฟอร์ม หรือ ASR (เช่น Whisper) และ AI provider ใด | ลำดับ: ซับจากแหล่ง (ถ้ามีและอนุญาต) → ASR ภายในเครื่อง (adapter); การคัดช่วง = ขอบประโยคจาก transcript + seeded random; LLM ใช้เฉพาะสร้างข้อความ (adapter, provider เลือกหลังวัดต้นทุน P1) | PO + Video Lead | Open |
| Q-03 | ค่าจำกัด Ingest | FR-02 "จำกัดความยาวและขนาด" ไม่มีตัวเลข | ไม่มีตัวเลข | เสนอทดสอบ: ต้นฉบับ ≤ 60 นาที, ≤ 2 GB, คลิป 15–90 วินาที, ≤ 10 คลิป/งาน (ยืนยันใน D02 หลัง P1) | PO | Open |
| Q-04 | Timezone ที่เลือกได้ใน MVP | §G | — | MVP เลือกได้เฉพาะ Asia/Bangkok; เก็บ IANA name + UTC เพื่อขยายภายหลัง | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-05 | Collision / การทำงานขนาน | FR-11, T13; §O.1 "โทรศัพท์หนึ่งเครื่องรับงานโพสต์ได้ครั้งละหนึ่งงาน" | PO ต้องการให้ "ทำขนานกันได้ตามจำนวน package" | **การตีความที่บันทึก (รอ PO ยืนยัน)**: งานโพสต์ทำขนานกันได้ข้ามโทรศัพท์/Session ได้สูงสุดตามขีดจำกัดของแพ็กเกจ (จำนวนเครื่อง × Session) และสอง Series ตั้งเวลาเดียวกันได้โดยไม่ถูกปฏิเสธ; **บนโทรศัพท์เครื่องเดียวยังทำทีละงาน** (ข้อจำกัดทางกายภาพของ UI automation และกติกา PRD §O.1) — รายการที่ชนบนเครื่องเดียวจะเข้าคิวต่อกันทันทีที่เครื่องว่าง (ไม่มี min gap 15 นาที) และ Preview แสดงเวลาที่คาดว่าจะเริ่มจริง | PO | Accepted with interpretation — confirm |
| Q-06 | นโยบายเลื่อน (Defer) | §G.7 | PO: "ทำขนานกันได้ตาม Q-05" | **การตีความที่บันทึก (รอ PO ยืนยัน)**: Offline/defer มีผลเฉพาะโทรศัพท์ที่ Offline — Series บนเครื่องอื่นทำงานขนานต่อไปตามปกติ; บนเครื่องที่ Offline ใช้ข้อเสนอเดิม (เลื่อนรายการที่พลาดและรายการต่อท้ายโดยรักษาระยะ X, ไม่มี Burst) หรือ Skip ตามที่ผู้ใช้เลือก | PO | Accepted with interpretation — confirm |
| Q-07 | "Auto mode ผ่านการตรวจระบบก่อนทุกคลิป" | FR-08, G3-05 | — | ตรวจอัตโนมัติ: media probe (9:16, มีเสียง, ความยาว), ข้อความไม่ว่าง/ไม่เกินความยาวช่อง, Encoding ไทยถูกต้อง, ไม่มีคำในรายการห้ามที่ผู้ใช้กำหนด; ไม่ผ่าน → NEEDS_ACTION | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-08 | Window ข้ามเที่ยงคืน / 24:00 | FR-10: MVP ไม่รองรับข้ามเที่ยงคืน; §G: 24:00 = สิ้นวัน | สอดคล้องกัน | รับ `end=24:00` เป็นสิ้นวัน; ปฏิเสธ end ≤ start | — | Proposed (ตาม PRD) |
| Q-09 | UI prototype | §L: "may be supplied separately" | ไม่มีไฟล์ใน repository | ใช้ Screen coverage ใน PRD (docs/ui-map.md); ถ้ามีต้นแบบภายหลังให้ map navigation ตามต้นแบบ | PO | Open |
| Q-10 | ข้อความคำยืนยันสิทธิ์ต้นฉบับ (Rights declaration) | FR-02 "เก็บคำยืนยันสิทธิ์" | ไม่มีถ้อยคำทางกฎหมาย | ใช้ข้อความ Draft ที่ระบุว่า Draft และเก็บ version ของข้อความกับทุก Job; PO/ที่ปรึกษากฎหมายต้องอนุมัติก่อน Pilot | PO | Open |
| Q-11 | Role QA/Support ใน MVP | §O.2 มี QA/Support; Team roles เป็นหลัง MVP | ไม่ขัดกัน: Team role ฝั่งลูกค้าเป็น P1, Platform role (Admin/Support) เป็น MVP | Platform roles: `admin`, `support` (read-limited); Workspace: owner เท่านั้น | — | Proposed |
| Q-12 | ซับซ้อนกับซับที่ฝังในต้นฉบับ | FR-07 ให้สร้างซับ | P1 พบต้นฉบับหลายรายการมีซับไทยฝังในภาพแล้ว; การเพิ่มซับจาก caption ทำให้ซับซ้อนกันสองชุด | Template มีตัวเลือก "เพิ่มซับจากคำบรรยาย" (เปิด/ปิด) ให้ผู้ใช้เลือกในขั้น "รูปแบบ" ของ Create พร้อม Preview; ค่าเริ่มต้น = เปิดเมื่อแหล่งมี caption track | PO | Proposed |

## 3. Engineering decisions (ย้อนกลับได้ — Proposed, ดำเนินงานต่อได้)

| ID | Decision | เหตุผล | ทางเลือกที่ไม่เลือก | Status |
|---|---|---|---|---|
| E-01 | ใช้ Reference stack ตาม PRD §B (React+TS+Vite, FastAPI, PostgreSQL+SQLAlchemy+Alembic, Redis, FFmpeg, yt-dlp, Python Agent) | Repository ว่าง ไม่มีสถาปัตยกรรมเดิมให้รักษา | — | Proposed |
| E-02 | Postgres เป็นแหล่งความจริงของ claim/lease/ledger/attempt; Scheduler ใช้ DB polling + `SELECT … FOR UPDATE SKIP LOCKED`; งาน Render ใช้ **Dramatiq + Redis** (retry/backoff, at-least-once) โดย task ทุกตัว idempotent ด้วย key ใน DB | ความถูกต้องของ lock/lease ต้องอยู่ในธุรกรรมเดียวกับสถานะ; Dramatiq เบากว่า Celery และรองรับ retry/time limit | Celery (หนักกว่า, config ซับซ้อน); arq (async only); Redis เป็น source of truth (ไม่ durable พอ) | Proposed |
| E-03 | Python runtime ใน container = 3.12; เครื่องพัฒนามี 3.14 (ทดสอบเครื่องมือ P0 เท่านั้น) | ไลบรารีบางตัว (เช่น ไลบรารีมีเดีย/ASR) อาจยังไม่มี wheel สำหรับ 3.14 | — | Proposed — ยืนยันใน compatibility.md |
| E-04 | Quota reserve เมื่อ Job ผ่าน SOURCE_VALIDATED และทราบความยาวต้นฉบับ (ก่อน DOWNLOADING ของไฟล์เต็ม); หน่วยเป็นจำนวนเต็ม (คลิป, วินาทีต้นฉบับ) | ต้องรู้ความยาวก่อนกันนาที; ป้องกันสองงานใช้ยอดเดียวกัน (T21) | กันตอน Render (เสี่ยง download ฟรีโดยไม่กันโควตา) | Proposed |
| E-05 | Scheduler คำนวณบน Server ฟังก์ชันเดียว (`schedule_core`) ใช้ทั้ง preview และ save | §G.2 ห้ามคำนวณแยกฝั่ง Browser | — | Proposed |
| E-06 | Package manager: npm (pnpm ไม่ได้ติดตั้ง) สำหรับ web; Python ใช้ `uv` หรือ pip-tools lockfile (เลือกตอน scaffold P1/P2) | ใช้เครื่องมือที่มีอยู่ | — | Proposed |
| E-07 | `make` ไม่มีบน Windows dev machine → มี `tasks.py` เป็น entry point เทียบเท่าทุก target (`py tasks.py <target>`) | PRD §I | — | Accepted by PRD §I |
| E-08 | Billing adapter แรก = `sandbox` ภายใน (ไม่ติดต่อผู้ให้บริการจริง) จนกว่า D06 ปิด | PRD §B, §M | — | Proposed |
| E-09 | Agent ↔ Server ใช้ HTTPS outbound polling (ไม่ใช้ WebSocket ใน MVP) | PRD §E | — | Proposed |
| E-10 | Agent เก็บ Token ใน Windows Credential Manager (ผ่าน `keyring`) | NF-02 | ไฟล์ config เข้ารหัสเอง | Proposed |
| E-11 | ขอบเขตคลิป (FR-04) ใช้ช่วงเงียบจริงของเสียง (ffmpeg `silencedetect`) แทนขอบ caption; threshold ปรับอัตโนมัติจาก -35 dB ทีละ 5 dB จนได้เฉลี่ย ≥1 pause/20 วินาที แต่ไม่ใกล้ค่าเฉลี่ยความดังเกิน 3 dB; บันทึก threshold ใน manifest | P1 พบว่า Thai auto-caption ของ YouTube ต่อกันไม่มีช่องว่างและตัดกลางคำ (2982 cues, gap ≥0.25s เพียง 4) และ Bilibili ไม่มี caption track; ต้นฉบับพากย์มีดนตรีพื้นหลัง (mean -16 dB) ทำให้ -35 dB เจอเพียง 3 pause | ขอบ caption (ใช้ไม่ได้กับข้อมูลจริง); ASR (Q-02 ยังเปิด) | Proposed |
| E-12 | ดาวน์โหลดเฉพาะช่วงที่เลือก (yt-dlp `download_ranges` + `force_keyframes_at_cuts`) และเสียงคุณภาพต่ำสุดสำหรับวิเคราะห์ ไม่ดาวน์โหลดต้นฉบับเต็ม | ต้นฉบับยาว 2–3.4 ชม.; ลด transfer/storage ต่อคลิป | ดาวน์โหลดไฟล์เต็ม | Proposed |
| E-13 | ฟอนต์ใน POC = Leelawadee UI (ฟอนต์ระบบ Windows ใช้ได้เฉพาะเครื่องนี้ ห้ามแจกจ่าย); ก่อน P3 เปลี่ยนเป็น Noto Sans Thai (SIL OFL) ที่บรรจุใน worker image | License | — | Proposed |
| E-14 | Render: 1080×1920 30fps H.264 CRF21 + AAC 128k; พื้นหลังเบลอ + ภาพต้นฉบับทั้งเฟรมอยู่ใต้แถบ Title 320px (tpl v2: ข้อความไม่ทับเนื้อหา เครดิต หรือ watermark ของต้นฉบับ — PRD §H); ข้อความทั้งหมดวาดด้วย libass จากไฟล์ .ass ที่ตัดบรรทัดไทยเอง (libass ตัดบรรทัดเฉพาะที่ช่องว่าง) | Thai shaping ถูกต้องผ่าน HarfBuzz; ข้อความไม่ล้นเฟรม | drawtext | Proposed |
| E-15 | Agent เขียน attempt journal แบบ write-ahead (fsync ก่อนทำแต่ละขั้น); recovery: หยุดก่อน SUBMITTING → RETRYABLE_FAILED, หยุดที่/หลัง SUBMITTING → UNKNOWN | FR-18, PRD §H | — | Proposed |
| E-16 | yt-dlp ต้องมี JS runtime สำหรับ YouTube → ใช้ Node ที่มีอยู่ (`js_runtimes: node`) และติดตั้ง `yt-dlp[default]` | yt-dlp เตือนว่า format อาจหายถ้าไม่มี runtime | deno | Proposed |

## 4. User changes ที่ override PRD

| วันที่ | การเปลี่ยนแปลง | ผลต่อ Acceptance criteria |
|---|---|---|
| 2026-10-06 | D04: ต้องรองรับทั้ง ADB UI automation และ TikTok Content Posting API แบบเลือกได้ (PRD §O.2 ระบุว่าห้ามใช้ Direct Post API แทนโดยอัตโนมัติ — การเปลี่ยนนี้คือให้ผู้ใช้เลือกเองหลังตรวจข้อกำหนด ไม่ใช่การสลับอัตโนมัติ) | Publishing adapter ต้องมี interface กลาง; G1-03/G5 ทดสอบ ADB ก่อน; API มี gate checks ของตนเองเมื่อเริ่ม |
| 2026-10-06 | Q-01: ไม่มีการแปลซับใน MVP | FR-07: ซับภาษาต้นฉบับ; G1-02 "ซับไทย" ตีความเป็น Title/Ending ภาษาไทย + ซับภาษาต้นฉบับที่แสดงผลถูกต้อง |
| 2026-10-06 | Q-05: ทำขนานตามจำนวนแพ็กเกจ | FR-11/T13: Collision บนเครื่องเดียว = เข้าคิว ไม่ใช่ปฏิเสธ; ยังห้าม Claim ซ้อนบนเครื่องเดียว |
