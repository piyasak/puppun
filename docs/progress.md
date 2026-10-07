# Progress

## Current phase: P1 — Feasibility POC (in progress). G0 = No (2/5), G1 = No (1/6).

Last updated: 2026-10-07

### Latest slice (2026-10-07, after commit 5ed272e)
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
