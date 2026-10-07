# Compatibility matrix

ตารางนี้บันทึกเฉพาะสิ่งที่รันจริงแล้วพร้อมวันที่ (ไม่รวมผลจาก mock)

## Development machine inventory (ตรวจ 2026-10-06 ด้วย `--version`)

| Tool | ผล | หมายเหตุ |
|---|---|---|
| OS | Windows 11 Pro 10.0.26100 | Windows baseline ของ Agent |
| Python | 3.14.5 (`py`, `python`) | E-03: container จะใช้ 3.12 |
| Node / npm | v26.1.0 / 11.12.1 | pnpm ไม่ได้ติดตั้ง |
| Docker | 28.3.2 — daemon ทำงาน (เปิด Docker Desktop 2026-10-06); `docker compose up -d` → postgres/redis/minio healthy, bucket `clipflow-media` private | |
| ADB | 1.0.41 — **ไม่พบอุปกรณ์** (ตรวจซ้ำ 2026-10-07 00:1x) | ต้องเสียบโทรศัพท์ + อนุญาต USB debugging |
| FFmpeg / FFprobe | 9.0.2 full build (gyan.dev, winget `Gyan.FFmpeg`) | libass/HarfBuzz ใช้ได้ (Thai shaping ถูกต้องจากภาพจริง) |
| yt-dlp | 2026.08.19 `[default]` ใน `.venv` + Node เป็น JS runtime | |
| make | **ไม่มี** | ใช้ `py tasks.py` (E-07) |
| PostgreSQL / Redis | ไม่มี native | ใช้ Docker Compose |
| git | 2.41.0 | ยังไม่ได้ตั้ง user.name/email |

## Source compatibility (G1-01) — รันจริง 2026-10-06/07

ลิงก์ที่ PO ระบุว่ามีสิทธิ์ใช้ (ส่งในแชท 2026-10-06) — Bilibili 3, YouTube 2 (**ยังไม่ครบเกณฑ์ ≥5 ต่อแพลตฟอร์ม**)

| Platform | Link type | Source ID | inspect | Duration source | ความยาว | ความละเอียด | Caption track | Date |
|---|---|---|---|---|---|---|---|---|
| Bilibili | bilibili.tv/th/video/<id> (BiliIntl) | 4796693831489536 | OK | ffprobe stream header (extractor ไม่ส่ง duration) | 113 นาที | 720×1280 | ไม่มี (มีซับไทยฝังในภาพ) | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4801047652604418 | OK | ffprobe stream header | 203 นาที | 854×478 | ไม่มี | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4800999597808128 | OK | ffprobe stream header | 141 นาที | 1280×720 | ไม่มี (มีซับไทยฝังในภาพ) | 2026-10-07 |
| YouTube | youtube.com/watch?v= | BkwOfQCFxE8 | OK | extractor | 134 นาที | 1080×1920 | th-orig (auto) — ต้นฉบับมีซับไทยฝังในภาพด้วย | 2026-10-07 |
| YouTube | youtube.com/watch?v= | bILzU5QwwsM | OK | extractor | 113 นาที | 1280×720 | th-orig (auto) | 2026-10-07 |

ข้อค้นพบ:
- ทุกต้นฉบับยาว 113–203 นาที เกินค่าเสนอ 60 นาที (Q-03/D02) — POC รันด้วย `--max-duration 14400`
- `bilibili.com` (จีน) ยังไม่ได้ทดสอบ — ลิงก์ที่ได้เป็น `bilibili.tv` ทั้งหมด
- YouTube Thai auto captions ต่อเนื่องไม่มีช่วงว่างและตัดกลางคำ → ใช้ขอบจากช่วงเงียบของเสียงแทน (E-11)
- ต้นฉบับหลายรายการมีซับฝังในภาพแล้ว → การเพิ่มซับซ้ำต้องเป็นตัวเลือกของผู้ใช้ (Q-12)

## Render results (G1-02) — `clipflow_worker.poc produce`, 2026-10-07

Template `tpl-default-v1` (ชุดแรก, `var/poc/`):

| Platform | Source ID | Source length | Captions | Pauses (threshold) | Seed | Clips | Clip lengths (s) | 1080×1920 H.264+AAC | Subtitle cues | Total time (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| bilibili | 4796693831489536 | 113 min | none | 632 (-25 dB) | 42 | 3/3 | 48.9, 51.1, 31.6 | yes | 0, 0, 0 | 104.55 |
| bilibili | 4800999597808128 | 141 min | none | 196 (-20 dB) | 7 | 3/3 | 54.8, 45.9, 55.1 | yes | 0, 0, 0 | 136.83 |
| bilibili | 4801047652604418 | 203 min | none | 638 (-25 dB) | 42 | 3/3 | 38.2, 35.5, 52.0 | yes | 0, 0, 0 | 118.89 |
| youtube | bILzU5QwwsM | 113 min | captions.th-orig.json3 | 2039 (-35 dB) | 42 | 3/3 | 48.3, 51.9, 57.1 | yes | 20, 23, 24 | 276.63 |
| youtube | BkwOfQCFxE8 | 134 min | captions.th-orig.json3 | 1626 (-35 dB) | 42 | 3/3 | 37.1, 38.6, 50.2 | yes | 6, 12, 14 | 238.24 |

Template `tpl-default-v2` (title band + ปิดซับได้, `var/poc_v2/`): BkwOfQCFxE8 3/3 clips (`--no-subtitles`), bILzU5QwwsM 1/1 — ตรวจภาพแล้ว title ไม่ทับเนื้อหา/watermark ของต้นฉบับ

Reproducibility (seed เดิม รันซ้ำ): ช่วงเวลาที่เลือกตรงกันทุกคลิปทั้ง 2 แหล่งที่ทดสอบ (bilibili 4800999597808128 seed 7; youtube bILzU5QwwsM seed 42); render hash ตรงกันสำหรับ Bilibili แต่ไม่ตรงสำหรับ YouTube (rendition ที่ YouTube ส่งให้ต่างกันได้) → clip ต้องเก็บ render hash ของตนเอง ไม่ใช้การ render ซ้ำเป็นหลักฐานไฟล์เดิม

Visual QA: ตรวจภาพนิ่งจากคลิปจริงด้วยตา (Thai title, วรรณยุกต์/สระบนล่าง, ending card, ซับ) — ไฟล์ภาพเก็บใน `var/evidence/` (ไม่ commit). **ยังไม่ได้เล่นบนโทรศัพท์** และยังไม่ได้ตรวจเสียงด้วยการฟังจากคนจริง

Benchmark (เครื่องพัฒนานี้, 15 คลิป, tpl v1):
```
clips=15, clip seconds total=696
range download per clip: mean 16.3s, max 37.8s
render per clip: mean 25.8s, max 34.9s (render/clip-second = 0.56)
inspect + captions + audio analysis per source: mean 48.9s, max 90.0s
```
ข้อมูลต้นทุนจริง (ค่า compute/transfer/AI เป็นเงิน) ยังไม่ได้คำนวณ — ไม่มีค่า AI ใน POC เพราะข้อความมาจาก template

## Android / TikTok matrix (G1-03, D03) — ยังไม่ได้ทดสอบ
| Device model | Android | TikTok app ver | ADB push | Gallery found | Thai input | Post verified | Date |
|---|---|---|---|---|---|---|---|
