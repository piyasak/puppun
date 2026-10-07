# Decision register

สถานะที่ใช้: **Open** (ยังไม่ตัดสิน) • **Proposed** (ทีมพัฒนาเสนอ รอผู้มีสิทธิ์ยืนยัน) • **Accepted** (มีผู้อนุมัติจริงบันทึกไว้) • **Superseded**
กฎ: Decision เชิงพาณิชย์/ขอบเขตต้องให้ PO ยืนยัน — Agent ห้ามเปลี่ยนเป็น Accepted เอง; Engineering decision ที่ย้อนกลับได้ใช้ Proposed และดำเนินงานต่อได้ แต่ต้องแจ้งใน Gate review

## 1. Product / commercial decisions (จาก PRD §O.14)

| ID | Decision | Phase ที่ต้องปิด | Owner | Status | ผลกระทบถ้ายังไม่ปิด |
|---|---|---|---|---|---|
| D01 | ชื่อแบรนด์จริง โดเมน และ Owner | P0 | PO | **Partially accepted (PO in chat, 2026-10-07)**: แบรนด์ = **punpun**; Owner/PO = ปิยศักดิ์ สุทธิประภา; โดเมน = รอ PO | ชื่อในโค้ด/เอกสารยังใช้ "ClipFlow" เป็นชื่อทำงานจนกว่าจะสั่งเปลี่ยน; UI ใช้ชื่อแบรนด์จาก config |
| D02 | ชนิดลิงก์ / ความยาวต้นฉบับ / ความยาวคลิป | P1 | PO | **Accepted (PO in chat, 2026-10-07)**: สุ่มช่วงเวลาจากต้นฉบับ 1 ลิงก์ ตัดคลิปละ **3–5 นาที** (180–300 วินาที) — ต้นฉบับยาวไม่จำกัดในเชิงธุรกิจ; เพดานทางเทคนิคดู E-17 | จำนวนคลิปสูงสุดต่องานยังไม่กำหนด (ผูกกับโควตาแพ็กเกจ D05) |
| D03 | Windows/Android/TikTok versions ที่รองรับ | P1 | PO + Agent Lead | **Accepted for P1 (PO in chat, 2026-10-07)**: รับรองเฉพาะ Windows 11 (เครื่อง QA) + POCO 25078PC3EG / Xiaomi HyperOS 2.0 / Android 15 + TikTok `com.ss.android.ugc.trill` 40.0.0; รุ่นอื่นต้องทดสอบก่อนเปิดให้ลูกค้าใช้ (Agent ต้องปฏิเสธ/เตือนเวอร์ชันที่ไม่อยู่ใน matrix — NF-10, T25) | ขยาย matrix ก่อน Pilot (G7) |
| D04 | รูปแบบช่องทางเผยแพร่ | P1 | PO | **Accepted (PO in chat, 2026-10-06)**: ต้องเลือกได้ทั้ง 2 ช่องทาง (ADB UI automation และ TikTok Content Posting API) — Implement ADB UI automation ก่อน; API เป็นงานถัดไปหลังตรวจข้อกำหนด/App audit ของ TikTok | ยังต้องมี dated terms review สำหรับ G1-05 |
| D05 | ราคาจริง โควตา จำนวนเครื่อง/Agent/Session ต่อแพ็กเกจ กำไรขั้นต้นเป้าหมาย | P6 | PO + Finance | Open | ใช้ Plan ทดสอบที่ระบุว่า Demo เท่านั้น |
| D06 | ผู้ให้บริการรับชำระ ภาษี เอกสาร Auto-renew Refund | P6 | PO + Finance | Open | Billing ใช้ sandbox adapter เท่านั้น |
| D07 | Pilot users, Support hours, Release cohort | P7/P8 | PO + Ops | Open | — |

## 2. Clarifications ที่พบระหว่างอ่าน PRD (ต้องการคำตอบจาก PO ก่อน G0-04 เป็น Yes)

| ID | ประเด็น | สิ่งที่ PRD ระบุ | ช่องว่าง / ความขัดกัน | ข้อเสนอ (Proposed) | Owner | Status |
|---|---|---|---|---|---|---|
| Q-01 | ภาษาซับไตเติล | FR-07 | ต้นฉบับอาจเป็นจีน/อังกฤษ | **ไม่มีการแปลใน MVP** — ซับใช้ภาษาต้นฉบับ; Title/Ending/Caption/Hashtag เป็นไทย; การแปลซับเป็นงานใน Phase ก่อน Production (backlog) | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-02 | ที่มา Transcript และการเลือกช่วง "AI" | FR-04 "เลือกช่วงแบบ AI หรือสุ่มจากช่วงที่ผ่านการคัดแล้ว" | ไม่ระบุว่า transcript มาจากซับของแพลตฟอร์ม หรือ ASR (เช่น Whisper) และ AI provider ใด | ลำดับ: ซับจากแหล่ง (ถ้ามีและอนุญาต) → ASR ภายในเครื่อง (adapter); การคัดช่วง = ขอบประโยคจาก transcript + seeded random; LLM ใช้เฉพาะสร้างข้อความ (adapter, provider เลือกหลังวัดต้นทุน P1) | PO + Video Lead | Open |
| Q-03 | ค่าจำกัด Ingest | FR-02 | ไม่มีตัวเลข | คลิป 180–300 วินาที (D02); ต้นฉบับสูงสุด 4 ชั่วโมงเป็นเพดานทรัพยากร (E-17) | PO | **Accepted (PO in chat, 2026-10-07)** (ความยาวคลิป) / Proposed (เพดานต้นฉบับ) |
| Q-04 | Timezone ที่เลือกได้ใน MVP | §G | — | MVP เลือกได้เฉพาะ Asia/Bangkok; เก็บ IANA name + UTC เพื่อขยายภายหลัง | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-05 | Collision / การทำงานขนาน | FR-11, T13; §O.1 | PO: "ทำขนานกันได้ตามจำนวน package" | งานโพสต์ทำขนานกันข้ามโทรศัพท์/Session ได้สูงสุดตามขีดจำกัดแพ็กเกจ; สอง Series ตั้งเวลาเดียวกันได้ไม่ถูกปฏิเสธ; บนโทรศัพท์เครื่องเดียวทำทีละงาน — รายการที่ชนเข้าคิวต่อทันทีที่เครื่องว่าง (ไม่มี min gap) และ Preview แสดงเวลาเริ่มที่คาดการณ์ | PO | **Accepted (PO in chat, 2026-10-07)** — ยืนยันการตีความ |
| Q-06 | นโยบายเลื่อน (Defer) | §G.7 | PO: "ทำขนานกันได้ตาม Q-05" | Offline/defer มีผลเฉพาะโทรศัพท์ที่ Offline — เครื่องอื่นทำงานต่อขนานกัน; บนเครื่องที่ Offline: Defer เลื่อนรายการที่พลาดและรายการต่อท้ายโดยรักษาระยะ X (ไม่มี Burst) หรือ Skip ตามที่ผู้ใช้เลือก | PO | **Accepted (PO in chat, 2026-10-07)** — ยืนยันการตีความ |
| Q-07 | "Auto mode ผ่านการตรวจระบบก่อนทุกคลิป" | FR-08, G3-05 | — | ตรวจอัตโนมัติ: media probe (9:16, มีเสียง, ความยาว), ข้อความไม่ว่าง/ไม่เกินความยาวช่อง, Encoding ไทยถูกต้อง, ไม่มีคำในรายการห้ามที่ผู้ใช้กำหนด; ไม่ผ่าน → NEEDS_ACTION | PO | **Accepted (PO in chat, 2026-10-06)** |
| Q-08 | Window ข้ามเที่ยงคืน / 24:00 | FR-10: MVP ไม่รองรับข้ามเที่ยงคืน; §G: 24:00 = สิ้นวัน | สอดคล้องกัน | รับ `end=24:00` เป็นสิ้นวัน; ปฏิเสธ end ≤ start | — | Proposed (ตาม PRD) |
| Q-09 | UI prototype | §L: "may be supplied separately" | ไม่มีไฟล์ใน repository | ใช้ Screen coverage ใน PRD (docs/ui-map.md); ถ้ามีต้นแบบภายหลังให้ map navigation ตามต้นแบบ | PO | Open |
| Q-10 | ข้อความคำยืนยันสิทธิ์ต้นฉบับ (Rights declaration) | FR-02 "เก็บคำยืนยันสิทธิ์" | ไม่มีถ้อยคำทางกฎหมาย | ใช้ข้อความ Draft ที่ระบุว่า Draft และเก็บ version ของข้อความกับทุก Job; PO/ที่ปรึกษากฎหมายต้องอนุมัติก่อน Pilot | PO | Open |
| Q-11 | Role QA/Support ใน MVP | §O.2 มี QA/Support; Team roles เป็นหลัง MVP | ไม่ขัดกัน: Team role ฝั่งลูกค้าเป็น P1, Platform role (Admin/Support) เป็น MVP | Platform roles: `admin`, `support` (read-limited); Workspace: owner เท่านั้น | — | Proposed |
| Q-12 | ซับซ้อนกับซับที่ฝังในต้นฉบับ | FR-07 | ต้นฉบับหลายรายการมีซับฝังแล้ว | Template มีตัวเลือก "เพิ่มซับจากคำบรรยาย" เปิด/ปิด ในขั้น "รูปแบบ" ของ Create พร้อม Preview; ค่าเริ่มต้นเปิดเมื่อแหล่งมี caption track | PO | **Accepted (PO in chat, 2026-10-07)** |
| Q-13 | การติดตั้ง helper พิมพ์ไทยบนโทรศัพท์ | FR-17, G1-03 | ต้องติดตั้ง app บนโทรศัพท์ | เครื่องพัฒนานี้คือ **เครื่อง QA**; ติดตั้ง ADBKeyboard (`senzhk/ADBKeyBoard` master `ADBKeyboard.apk`, 17,374 bytes, SHA-256 E698ADEA…CDC59); บันทึก IME เดิม (Gboard) และคืนค่าหลังทดสอบ | PO | **Accepted (PO in chat, 2026-10-07)** |
| Q-14 | Terms review (G1-05) และคำยืนยันสิทธิ์ต้นฉบับ | FR-02, G1-05, §O.14 | ผู้พัฒนาเสนอให้ตรวจข้อกำหนด YouTube/Bilibili/TikTok แบบลงวันที่ | PO: **ไม่ต้องทำ terms review**; คำยืนยันสิทธิ์ให้ผู้ใช้ยอมรับอัตโนมัติ — Implement เป็นการยอมรับข้อตกลง (มี version) ครั้งเดียวตอนสมัคร แล้วระบบแนบ version ที่ยอมรับเข้ากับทุก Job อัตโนมัติ (ยังเก็บหลักฐานตาม FR-02 แต่ไม่ถามซ้ำทุกงาน) | PO | **Accepted (PO in chat, 2026-10-07)** — PO รับความเสี่ยงด้านข้อกำหนดแพลตฟอร์ม/ลิขสิทธิ์ (ดู §4) |
| Q-15 | แบ่งงานระหว่าง Agent กับ Server หลัง R-01 | R-01 | PRD §O.7 วาง Render worker ไว้ฝั่ง Server | **ข2**: Agent ดาวน์โหลด + วิเคราะห์ + render บนเครื่องลูกค้า แล้วอัปโหลดเฉพาะคลิปที่เสร็จ (พร้อม sha256) ให้ Server ใช้ preview/approve/audit; Server คุม Job state, quota, approval, schedule | PO | **Accepted (PO in chat, 2026-10-07)** |
| Q-16 | ใช้ cookies บัญชี YouTube ของผู้ใช้เมื่อเจอ bot check | R-01 | ต้องใช้ session login ของผู้ใช้ | Opt-in ต่อเครื่อง, อ่านจาก browser บนเครื่องลูกค้าเท่านั้น, ไม่เก็บ/ไม่ส่งขึ้น server, ผู้ใช้รับทราบว่าบัญชีอาจถูก YouTube จำกัด | PO | Open |
| Q-17 | ลูกค้าโหลดวิดีโอมาเอง แล้วให้ระบบตัดและโพสต์อัตโนมัติ | PO request 2026-10-07 (เพิ่มขอบเขต) | PRD รับเฉพาะลิงก์ YouTube/Bilibili | แหล่งที่มาชนิดที่ 3 "ไฟล์ของลูกค้า": เลือกไฟล์บนเครื่องที่ติดตั้ง Agent → ตรวจด้วย ffprobe (ไม่เชื่อนามสกุลไฟล์), จำกัดขนาด 8 GB และความยาว 4 ชม., ใช้ SHA-256 ของไฟล์เป็น source ID, เก็บเฉพาะชื่อไฟล์ไม่เก็บ path เต็ม, ซับจากไฟล์ .srt ชื่อเดียวกัน (ถ้ามี) → ตัดและ render ด้วย pipeline เดียวกัน → โพสต์ตามตาราง; คำยืนยันสิทธิ์ตาม Q-14 | PO | **Accepted (PO in chat, 2026-10-07)** |
| Q-18 | G1-06 ต้นทุนเป็นเงิน | G1-06 | — | PO ให้เลื่อนไว้ก่อน (ข้ามไปทำส่วนอื่น) — G1-06 ยังเป็น No และ G1 ผ่านไม่ได้จนกว่าจะทำ | PO | **Accepted (PO in chat, 2026-10-07)** (deferred) |

| Q-19 | อนุญาตโพสต์ทดสอบจริง | G1-03, G1-04, PRD §A/§C (ห้ามโพสต์สาธารณะเพื่อพิสูจน์ Gate) | — | **1 โพสต์** ด้วยบัญชีทดสอบที่ login อยู่ในโทรศัพท์ QA (PO แจ้ง 2026-10-06); ตั้งการมองเห็น "เฉพาะฉัน" ตามหลัก PRD; ใช้โพสต์นี้ทดสอบทั้งการตรวจผลและกรณีหลุดหลัง Submit (UNKNOWN → resolve ด้วยหลักฐาน); Agent ไม่ลบโพสต์เอง (การลบถาวรเป็นของผู้ใช้) | PO | **Accepted (PO in chat, 2026-10-07)** |
| Q-20 | ผู้รับผิดชอบทุกบทบาท | G0-05 | — | PO, Tech Lead, QA, Video/Agent Lead, Ops/Finance = ปิยศักดิ์ สุทธิประภา; งบ POC ยังไม่ระบุ | PO | **Accepted (PO in chat, 2026-10-07)** |

| Q-21 | Marker ในแคปชันเพื่อยืนยันผลโพสต์ | PRD §H, FR-18 | P1 ใช้ marker สั้น (เช่น `cf2143e0`) ในแคปชันเพื่อผูกโพสต์กับ attempt; เปลี่ยนแคปชันของผู้ใช้เล็กน้อย | ข้อเสนอ: คงไว้แบบสั้นท้ายแคปชัน (ทางเลือก: จับคู่ด้วยเวลา+ภาพปก ซึ่งอาจผิดพลาดเมื่อโพสต์ใกล้กัน) | PO | Open |

| Q-22 | เริ่ม P2 ทั้งที่ G1-06 (ต้นทุน) ยังเป็น No | PRD §O.10: P2 ขึ้นกับ G1 Yes | G1 = 5/6 | PO เลือกข้ามไปก่อน: เริ่ม P2 ได้; G1 ยังบันทึกเป็น No; G1-06 ต้องทำก่อนอนุมัติราคา/โควตาใน G6 (D05) | PO | **Accepted (PO in chat, 2026-10-07)** — PO รับความเสี่ยงด้านราคา |

| Q-23 | ประหยัดพลังงานโทรศัพท์ | PO request 2026-10-07 (เพิ่มขอบเขต) | — | ก่อนเริ่มงาน: เปิด Wi-Fi และรอจน Android รายงาน VALIDATED (ไม่ออนไลน์ภายใน 45s → NEEDS_ACTION ก่อน Submit); หลังโพสต์และยืนยันผล: ปิดแอป TikTok (force-stop) และปิด Wi-Fi; **ไม่ปิด** ขณะ attempt ยังเป็น SUBMITTING/VERIFYING/UNKNOWN (อาจยังอัปโหลดอยู่และต้องตรวจผล); ไม่ปิด Wi-Fi ถ้า ADB เชื่อมผ่าน Wi-Fi; เปิดใช้เป็นค่าเริ่มต้นต่อเครื่อง (ปิดได้) | PO | **Accepted (PO in chat, 2026-10-07)** |

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
| E-17 | เพดานทรัพยากรต้นฉบับ 4 ชั่วโมง (`DEFAULT_MAX_DURATION_S`) — ต้นฉบับจริงที่ทดสอบยาวสุด 203 นาที; ปรับได้ต่อแพ็กเกจภายหลัง | FR-02 ยังต้องมีขีดจำกัด; D02 ไม่จำกัดความยาวเชิงธุรกิจ | ไม่จำกัด (เสี่ยงต้นทุน/เวลา) | Proposed |
| E-18 | ตาม Q-15 (ข2): โมดูล media (`services/worker/clipflow_worker`: source, segments, textlayout, render, cooldown, local_source) จะถูกบรรจุใน Windows Agent ตอน P5 packaging — ยังไม่ย้ายไฟล์ใน P1; Server ไม่มี render worker ใน MVP (Redis queue ยังใช้สำหรับงาน server เช่น schedule/notification) | ลดต้นทุน server และแก้ R-01; โพสต์ใช้ไฟล์บนเครื่องเดียวกัน | render บน server (ข1) | Proposed |
| E-19 | Bot check/429 = `SOURCE_RATE_LIMITED` แยกจาก `SOURCE_NOT_ACCESSIBLE`; Agent บันทึก cool-down ต่อแพลตฟอร์ม 1→2→4→6 ชม. (สูงสุด) และไม่ส่งคำขอระหว่าง cool-down; reset เมื่อดาวน์โหลดสำเร็จ | R-01; ข้อความ YouTube ใช้ apostrophe โค้ง ทำให้ marker เดิมไม่ตรงและถูกรายงานเป็น "เข้าถึงไม่ได้" | retry ทันที | Proposed |
| E-20 | ส่งไฟล์เข้าโทรศัพท์ผ่าน staging: push ไป `Movies/ClipFlow/.incoming/<uuid>.part` (มี .nomedia) → ตรวจ SHA-256 บนเครื่อง → `mv` เป็นชื่อจริง; ล้าง `.part` ที่ค้างตอน Agent เริ่ม; P5: ผูก process ลูก (adb) กับ Windows Job Object ให้ตายพร้อม Agent | Fault test จริง: process `adb push` ที่เป็นลูกทำงานต่อหลัง Agent ถูก kill แล้วเขียนไฟล์ที่ไม่ได้ตรวจลง Gallery | push ตรงไปชื่อจริง | Proposed |

## 3b. Risks found in P1 (ต้องการการตัดสินใจจาก PO)

| ID | ความเสี่ยง | หลักฐาน | ผลกระทบ | ทางเลือก (ยังไม่ได้ทำ) | Owner | Status |
|---|---|---|---|---|---|---|
| R-01 | YouTube จำกัดการดาวน์โหลดซ้ำจาก IP เดียว (bot check "Sign in to confirm you're not a bot"; ก่อนหน้านั้นสตรีมถูกตัดกลางทางโดยไม่มี error) | 2026-10-07 หลังดาวน์โหลด ~15 ช่วง + เสียง 5 แหล่งในวันเดียว — `docs/compatibility.md` | Server ที่ดาวน์โหลดให้ลูกค้าหลายรายจาก IP เดียวจะถูกบล็อกบ่อย; FR-03 ต้องแสดงสถานะเข้าถึงไม่ได้และไม่ retry ไม่จำกัด (ทำแล้ว) | (ก) จำกัดอัตราดาวน์โหลด/คิวต่อ IP; (ข) ดาวน์โหลดบนเครื่องลูกค้าผ่าน Agent; (ค) ใช้ cookies บัญชี YouTube — ต้องใช้ credential ผู้ใช้และขัดหลักไม่เก็บ credential จึงไม่ทำโดยไม่มีการตัดสินใจ | PO + Tech Lead | **Decided (PO in chat, 2026-10-07): ข — ดาวน์โหลดบนเครื่องลูกค้าผ่าน Agent** (IP ที่บ้าน/สำนักงานของลูกค้าเอง, ปริมาณต่อ IP ต่ำ); ไม่ใช้ proxy pool/การหมุน IP เพื่อหลบ bot check (PRD §O.2 ไม่รวมการข้ามระบบป้องกัน); เมื่อเจอ bot check ให้หยุด รอ cool-down และแจ้งผู้ใช้; cookies ของผู้ใช้ใช้ได้เฉพาะแบบ opt-in บนเครื่องลูกค้าเท่านั้น ไม่ส่งขึ้น server — รอ PO ตัดสินว่าจะเปิดหรือไม่ (Q-16) |

## 4. User changes ที่ override PRD

PRD v1.1 อนุมัติโดย ปิยศักดิ์ สุทธิประภา (PO) วันที่ 7/10/2026 — รายการด้านล่างเป็นการเปลี่ยนแปลงที่ PO สั่งเพิ่มเติม

| วันที่ | การเปลี่ยนแปลง | ผลต่อ Acceptance criteria |
|---|---|---|
| 2026-10-06 | D04: ต้องรองรับทั้ง ADB UI automation และ TikTok Content Posting API แบบเลือกได้ (PRD §O.2 ระบุว่าห้ามใช้ Direct Post API แทนโดยอัตโนมัติ — การเปลี่ยนนี้คือให้ผู้ใช้เลือกเองหลังตรวจข้อกำหนด ไม่ใช่การสลับอัตโนมัติ) | Publishing adapter ต้องมี interface กลาง; G1-03/G5 ทดสอบ ADB ก่อน; API มี gate checks ของตนเองเมื่อเริ่ม |
| 2026-10-06 | Q-01: ไม่มีการแปลซับใน MVP | FR-07: ซับภาษาต้นฉบับ; G1-02 "ซับไทย" ตีความเป็น Title/Ending ภาษาไทย + ซับภาษาต้นฉบับที่แสดงผลถูกต้อง |
| 2026-10-06 | Q-05: ทำขนานตามจำนวนแพ็กเกจ | FR-11/T13: Collision บนเครื่องเดียว = เข้าคิว ไม่ใช่ปฏิเสธ; ยังห้าม Claim ซ้อนบนเครื่องเดียว |
| 2026-10-07 | G0 sign-off: ปิยศักดิ์ สุทธิประภา อนุมัติ Gate 0 | P2 งานฐานระบบเริ่มได้เมื่อ G1 ผ่าน (ลำดับ Phase) |
| 2026-10-07 | Q-23: Agent เปิด Wi-Fi ก่อนงาน และปิดแอป + Wi-Fi หลังผลยืนยันแล้ว | FR-17/FR-18: release เฉพาะสถานะที่จบแล้ว; UI Devices มีสวิตช์ "ประหยัดพลังงาน" ต่อเครื่อง |
| 2026-10-07 | Q-22: เริ่ม P2 โดย G1 ยังไม่ผ่าน (เหลือ G1-06 ต้นทุน) | ลำดับ Phase: P2 ได้รับอนุญาตแบบ override; G6-01 ต้องใช้ผล G1-06 |
| 2026-10-07 | G1-03: โทรศัพท์ 1 รุ่นเพียงพอ (PRD กำหนด ≥2 รุ่น) | หลักฐาน G1-03 = POCO 25078PC3EG; ความเสี่ยงความเข้ากันได้กับรุ่นอื่นย้ายไปตรวจใน G5-01/G7 |
| 2026-10-07 | D02: คลิปยาว 3–5 นาที (PRD/ข้อเสนอเดิม 15–90 วินาที) | FR-04/FR-05/G1-02: เกณฑ์ความยาวคลิป = 180–300 วินาที |
| 2026-10-07 | Q-15 (ข2): ดาวน์โหลด วิเคราะห์ และ render บนเครื่องลูกค้าผ่าน Agent (PRD §O.7 วาง render ไว้ server) | NF-03: SSRF guard ยังใช้ใน Agent; G3-01/G3-03 ทดสอบบน Agent; Server ต้องตรวจ sha256 ของคลิปที่อัปโหลดและผูกกับ render version; quota ยังกันที่ Server ก่อน Agent เริ่ม; อัปเดตแพ็กเกจ Agent ต้องรวม yt-dlp ใหม่ (NF-10) |
| 2026-10-07 | Q-17: เพิ่มแหล่งที่มา "ไฟล์ของลูกค้า" นอกจากลิงก์ | FR-02/FR-03 ใช้กับไฟล์ด้วย (ตรวจชนิด/ขนาด/ความยาว, error แยก UNSUPPORTED_FILE); UI Create ขั้นที่ 1 ต้องมีตัวเลือก "ลิงก์" หรือ "ไฟล์บนเครื่อง Agent" |
| 2026-10-07 | Q-14: ยกเลิก terms review ของ G1-05; PO ตัดสินว่ารูปแบบบริการ (ดาวน์โหลดจาก YouTube/Bilibili + โพสต์ผ่าน ADB UI automation) เปิดใช้ได้ และรับความเสี่ยงเอง; rights declaration = ยอมรับครั้งเดียวตอนสมัครและแนบอัตโนมัติกับทุก Job | G1-05: หลักฐาน = PO decision ที่บันทึกนี้ (ไม่มี dated review); FR-02: เก็บ terms version ที่ยอมรับกับ Job แทนการติ๊กทุกงาน; ความเสี่ยง §O.14 "ช่องทางโพสต์อัตโนมัติและข้อกำหนดบริการ" และ "สิทธิ์ใช้วิดีโอ" ยังคงอยู่และ PO เป็นเจ้าของ |
