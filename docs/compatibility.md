# Compatibility matrix

ตารางนี้บันทึกเฉพาะสิ่งที่รันจริงแล้วพร้อมวันที่ (ไม่รวมผลจาก mock)

## Development machine inventory (ตรวจ 2026-10-06 ด้วย `--version`)

| Tool | ผล | หมายเหตุ |
|---|---|---|
| OS | Windows 11 Pro 10.0.26100 | Windows baseline ของ Agent |
| Python | 3.14.5 (`py`, `python`) | E-03: container จะใช้ 3.12 |
| Node / npm | v26.1.0 / 11.12.1 | pnpm ไม่ได้ติดตั้ง |
| Docker | 28.3.2 — daemon ทำงาน (เปิด Docker Desktop 2026-10-06); `docker compose up -d` → postgres/redis/minio healthy, bucket `clipflow-media` private | |
| ADB | 1.0.41 — โทรศัพท์ 1 เครื่องเชื่อมผ่าน USB 2026-10-07 19:2x (ต้องกดอนุญาต USB debugging บนเครื่องก่อน: สถานะ unauthorized → device) | |
| FFmpeg / FFprobe | 9.0.2 full build (gyan.dev, winget `Gyan.FFmpeg`) | libass/HarfBuzz ใช้ได้ (Thai shaping ถูกต้องจากภาพจริง) |
| yt-dlp | 2026.08.19 `[default]` ใน `.venv` + Node เป็น JS runtime | |
| make | **ไม่มี** | ใช้ `py tasks.py` (E-07) |
| PostgreSQL / Redis | ไม่มี native | ใช้ Docker Compose |
| git | 2.41.0 | repo-local user = piyasak (2026-10-07) |
| Network | 2026-10-07 ~01:00 ถูก proxy `ssproxy.boonrawd.co.th:8080` ตอบ 407; เซสชันถัดมาไม่มี proxy และออกอินเทอร์เน็ตได้ | ถ้า proxy กลับมา error จะเป็น DOWNLOADER_ERROR "network error (retryable)" |

## Source compatibility (G1-01) — รันจริง 2026-10-06/07

ลิงก์ที่ PO ระบุว่ามีสิทธิ์ใช้: ชุดที่ 1 (2026-10-06) Bilibili 3, YouTube 2 — ทดสอบแล้ว; ชุดที่ 2 (2026-10-07) YouTube 3, Bilibili 2 — ทดสอบแล้วหลัง proxy หาย; **รวม 5/5 YouTube และ 5/5 Bilibili อ่านได้ทั้งหมด**

| Platform | Link type | Source ID | inspect | Duration source | ความยาว | ความละเอียด | Caption track | Date |
|---|---|---|---|---|---|---|---|---|
| Bilibili | bilibili.tv/th/video/<id> (BiliIntl) | 4796693831489536 | OK | ffprobe stream header (extractor ไม่ส่ง duration) | 113 นาที | 720×1280 | ไม่มี (มีซับไทยฝังในภาพ) | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4801047652604418 | OK | ffprobe stream header | 203 นาที | 854×478 | ไม่มี | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4800999597808128 | OK | ffprobe stream header | 141 นาที | 1280×720 | ไม่มี (มีซับไทยฝังในภาพ) | 2026-10-07 |
| YouTube | youtube.com/watch?v= | BkwOfQCFxE8 | OK | extractor | 134 นาที | 1080×1920 | th-orig (auto) — ต้นฉบับมีซับไทยฝังในภาพด้วย | 2026-10-07 |
| YouTube | youtube.com/watch?v= | bILzU5QwwsM | OK | extractor | 113 นาที | 1280×720 | th-orig (auto) | 2026-10-07 |
| YouTube | youtube.com/watch?v= | WsE6xveFcGE | OK (retest after proxy cleared) | extractor | 232 นาที | 1920×1080 | th-orig (auto) | 2026-10-07 |
| YouTube | youtube.com/watch?v= | QuiyZPI3TNI | OK | extractor | 158 นาที | 1920×1080 | th-orig (auto) | 2026-10-07 |
| YouTube | youtube.com/watch?v= | PBES5k67dhI | OK | extractor | 101 นาที | 1920×1080 | th-orig (auto) | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4789561647301632 | OK | ffprobe stream header | 111 นาที | 1280×720 | ไม่มี | 2026-10-07 |
| Bilibili | bilibili.tv/th/video/<id> | 4800844531374592 | OK | ffprobe stream header | 61 นาที | 720×1280 | ไม่มี | 2026-10-07 |

ข้อค้นพบ:
- ทุกต้นฉบับยาว 61–232 นาที (WsE6xveFcGE 232 นาทีใกล้เพดาน 4 ชม.) — อยู่ในเพดานทรัพยากร 4 ชม. (E-17); D02 กำหนดความยาวคลิป 3–5 นาที ไม่จำกัดความยาวต้นฉบับเชิงธุรกิจ
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

## D02 clip length 3–5 minutes — 2026-10-07

### ผลิตจากต้นฉบับจริง (หลัง proxy หาย, 2026-10-07 17:05–18:15)

| Source | Run | Clips | ความยาวที่ได้ (s) เทียบช่วงที่เลือก | Render time (s) | ผล |
|---|---|---|---|---|---|
| bilibili 4800844531374592 (61 นาที, 720×1280) | 1 | 3/3 | 182.8 / 194.4 / 244.3 — ตรงช่วงภายใน 0.1s | 73, 74, 92 | OK — ตรวจภาพ: title band, credit ต้นฉบับไม่ถูกทับ, ending card |
| youtube PBES5k67dhI (101 นาที, 1920×1080) | 1 | 3 "สำเร็จ" | 190.9 / 262.1 OK; **clip_03 = 33.4s แต่ช่วงที่เลือก 230.7s** | 106, 208, 1429 | **BUG**: range download ใช้ 970s แล้วได้ไฟล์ไม่ครบ (video 33.3s / audio 29.7s) โดย yt-dlp ไม่แจ้ง error และ pipeline รายงาน 3/3 |
| youtube PBES5k67dhI | 2 (หลังแก้) | 2/3 แล้วหยุด | 190.9 / 262.1 (ไฟล์ขนาดเท่ารอบ 1) | ~90, ~120 | clip 3: YouTube ตอบ "Sign in to confirm you're not a bot" → SOURCE_NOT_ACCESSIBLE, job หยุด ไม่สร้างไฟล์เสีย |

| bilibili 4800844531374592 | 3 (v3, หลังแก้ความละเอียด) | 3/3 | 182.8 / 194.4 / 244.3 — ช่วงเดียวกับ run 1 (seed 42) | ~70–90 | OK — ต้นฉบับ 720×1280 (เดิมได้ 480×852) |
| youtube PBES5k67dhI | 3 (v3, ~2.5 ชม. หลัง bot check) | **3/3** | 190.9 / 262.1 / 230.7 — ตรงช่วง | — | OK; มีเพียง 22 pauses (-20 dB, ดนตรีตลอด) แต่ยังเลือกได้ 3 ช่วง; ต้นฉบับมีซับฝังในภาพ + caption track → ค่าเริ่มต้นเปิดซับ (Q-12) ทำให้ซับซ้อน 2 ชุด |
| **ไฟล์ของลูกค้า** (Q-17) `ละครที่ลูกค้าโหลดมาเอง.mp4` 158 MB, 61 นาที (จำลองโดยดาวน์โหลด bilibili 4800844531374592 ทั้งไฟล์) | 1 | 3/3 | 207.4 / 191.1 / 230.1 — ตรงช่วง | 72, 64, 78 (ไม่มีขั้นดาวน์โหลด) | OK — manifest เก็บเฉพาะชื่อไฟล์ + SHA-256, ไม่มี path เต็ม; ชื่อไฟล์ภาษาไทยใช้ได้ |

**BUG (แก้แล้ว 2026-10-07): ความละเอียดของต้นฉบับแนวตั้ง** — ตัวกรอง `height<=1080` ทำให้ต้นฉบับแนวตั้ง 720×1280 / 1080×1920 ถูกดาวน์โหลดที่ 480×852 แล้วขยายเป็น 1080×1920 (ภาพเบลอ) ในทุกคลิปก่อนหน้านี้ที่มาจากต้นฉบับแนวตั้ง; เปลี่ยนเป็นจำกัดด้านสั้น (`format_sort res:1080`) — ตรวจจริง: BkwOfQCFxE8 → 1080×1920, PBES5k67dhI → 1920×1080, bilibili 4800844531374592 → 720×1280

ข้อสังเกตจากภาพ: emoji ในชื่อต้นฉบับ (เช่น 💥) แสดงเป็นสัญลักษณ์เส้นเพราะฟอนต์ไทยไม่มี emoji สี → P3: ตัด emoji ออกจากข้อความที่ฝังในภาพ หรือใช้ฟอนต์ fallback

แก้แล้ว: `media.duration_gaps()` ตรวจความยาว container/video/audio — range ที่ดาวน์โหลดต้องตรงช่วง ±1.0s (ไม่ตรง → retry 1 ครั้ง แล้ว DOWNLOADER_ERROR) และไฟล์ที่ render ต้องตรง ±0.5s (ไม่ตรง → RenderError/RENDER_MISMATCH); ทดสอบกับไฟล์เสียจริงแล้วจับได้ทั้งสองจุด

ข้อค้นพบด้านการดำเนินงาน: หลังดาวน์โหลดจาก YouTube ต่อเนื่องจาก IP เดียว YouTube เริ่มบังคับ bot check (และอาจตัดสตรีมกลางทางก่อนหน้านั้น) — ความเสี่ยง R-01 ใน decisions.md

### ตรวจแบบ offline (ก่อน network ใช้ได้):

Segment selection บนเสียงจริงที่ดาวน์โหลดไว้แล้ว (threshold ตาม manifest, `pause_candidates(180, 300)`, seed 42, 3 คลิป):

| Source | Pauses | Candidates 180–300s | Selected (start s, length s) | Insufficient |
|---|---|---|---|---|
| bilibili 4796693831489536 | 632 (-25 dB) | 7886 | (2008, 283), (3219, 204), (6376, 211) | no |
| bilibili 4800999597808128 | 196 (-20 dB) | 601 | (5591, 225), (6674, 268), (7421, 185) | no |
| bilibili 4801047652604418 | 638 (-25 dB) | 7678 | (991, 191), (1669, 290), (4685, 182) | no |
| youtube BkwOfQCFxE8 | 1626 (-35 dB) | 39205 | (385, 183), (4153, 201), (5391, 218) | no |
| youtube bILzU5QwwsM | 2039 (-35 dB) | 71135 | (1141, 242), (2354, 224), (4199, 260) | no |

Render 300 วินาทีจากวิดีโอสังเคราะห์ (ffmpeg testsrc2 1280×720 + sine, ซับไทย 29 cues): ผล 1080×1920, 300.00s, H.264/AAC; ตรวจภาพที่ 286s (title + ซับ) และ 299s (ending card, ไม่มีซับทับ) ถูกต้อง; **render ใช้ 236.3s ต่อคลิป 5 นาที (≈0.79× realtime)** บนเครื่องนี้ → งาน 3 คลิป × 5 นาที ≈ 12 นาที render ต่อ Job ต่อ worker 1 ตัว (ข้อมูลสำหรับ G1-06/capacity)

### Same render, same bytes (2026-10-15)
Approvals and schedule items are bound to the render sha256, so a remake must be the same file. Same segment, lossless source (ffv1/flac, 640×360 → 1080×1920, 20 s), FFmpeg 6.1.1 (Ubuntu 24.04 runner) and 9.0.2 (this PC):

| Render args | Result |
|---|---|
| before (`-threads cpu_count//2`, CPU's own SIMD) | hash changes with the thread count (this PC: 10/2/1 threads → 3 hashes); AAC differs by SIMD level (AVX2 vs AVX vs SSE2 on this PC); on AVX-512 runners (Xeon 8573C/8370C, EPYC 9V74) the video differed **from one render to the next on one VM** (3 renders → 3 hashes) — the cause of the CI failure of `test_reset_remakes_a_deleted_file_with_the_same_hash` (run 38743242112) |
| after (`render.py`: x264 `cpu-independent=1` + 4 threads, FFmpeg `-cpuflags` SSE2 on x86-64, `+bitexact`, `-map_metadata -1`) | 12 runners, 5 CPU models (EPYC 7763/9V74/9V45, Xeon 8573C/8370C; AVX2 and AVX-512), 3 renders each + 1 vs 2 filter threads: **one video (md5 5c37d961) and one audio stream** everywhere; equals x264's plain-C output |

Cost on this PC (i7-13700H, 60 s clip): SSE2 FFmpeg ≈ +10% (27.5 s → ~31 s); `cpu-independent` no measurable difference. Different FFmpeg/x264/libass versions still make different bytes (the Agent ships one pinned FFmpeg build, Q-46). Changing the args changes the hash of new renders only; clips already rendered keep their stored files and hashes.

## API stack (P2.1) — ทดสอบ 2026-10-07
| Component | Version | ผล |
|---|---|---|
| Python (host) | 3.14.5 | 28 integration (+1 skip: ไม่มี live token) + 92 unit ผ่าน (container runtime 3.12 ตาม E-03 ยังไม่ได้ทดสอบ) |
| FastAPI / Starlette / Pydantic | 0.142.2 / 1.7.0 / 2.13.5 | ผ่าน |
| SQLAlchemy / Alembic / psycopg | 2.1.3 / 1.20.0 / 3.3.6 (binary) | ผ่าน; `alembic check` ไม่มี drift |
| PyJWT[crypto] / cryptography / uvicorn | 2.15.1 / 50.0.2 / 0.54.0 | ผ่าน; ES256 verify กับ JWKS ของ Supabase จริง |
| Supabase Auth (project `punpun`, ap-southeast-1) | JWKS: 1 key ES256 (P-256), 2026-10-07 | live: ปฏิเสธ token ที่ไม่ได้เซ็นโดยโปรเจกต์; end-to-end กับผู้ใช้จริงยังไม่ได้ทดสอบ |
| PostgreSQL (compose) | 16.15 | ผ่าน |

## Web + E2E (P2) — ทดสอบ 2026-10-07
| Component | Version | ผล |
|---|---|---|
| Node / npm | 26.1.0 / 11.12.1 | ผ่าน |
| React / TypeScript / Vite | 19.2 / 6.0 / 8.3.3 | build ผ่าน |
| @supabase/supabase-js / react-router-dom | 2.117 / 7.18 | ผ่าน (flowType implicit) |
| @playwright/test + Microsoft Edge (channel msedge) | 1.63 | E2E 2/2 ผ่าน |
| Supabase cloud `punpun` + Microsoft 365 mailbox | 2026-10-07 | สมัคร/ยืนยัน/onboarding ผ่าน (PO); ตัวสแกน M365 เปิดลิงก์ยืนยันเองหลังผู้ใช้ → ต้องทำ E-28 |
| Supabase CLI (local) | 2.120.0, postgres 17.11.0.004 image | auth + Mailpit ผ่าน; ES256 local key |

## Android / TikTok matrix (G1-03, D03)
| Device model | Android | TikTok app ver | ADB push + SHA-256 | Gallery found | Thai input | Post verified | Date |
|---|---|---|---|---|---|---|---|
| POCO 25078PC3EG (Xiaomi HyperOS 2.0, product dew_p_global) | 15 (SDK 35) | com.ss.android.ugc.trill 40.0.0 | OK — 68 MB 9s, 158 MB 14s | OK (MediaStore) | OK — ADBKeyboard B64: ไทย + 🎬 + hashtag ตรงตามที่อนุมัติ | OK — 1 โพสต์ "เฉพาะฉัน", ตรวจด้วย marker บนโปรไฟล์ (runbook) | 2026-10-07 |
| รุ่นที่ 2 | — | — | — | — | — | — | ยังไม่มีเครื่อง |

### Power saving (Q-23) บนเครื่องจริง, 2026-10-07
| Run | เริ่มจาก | ผล |
|---|---|---|
| A | Wi-Fi เปิด, TikTok ทำงาน | prepare: online แล้ว → dry-run → CANCELLED → release: TikTok force-stop (ไม่มี pid), Wi-Fi ปิด — 12s |
| B | Wi-Fi ปิด | prepare: เปิด Wi-Fi + รอ VALIDATED → dry-run → release: ปิดแอป + Wi-Fi — 14s |
| BUG (แก้แล้ว) | Wi-Fi ปิด | ตัวตรวจ online เดิมรายงาน online=true ขณะ Wi-Fi ปิด เพราะ "Transports: WIFI ... VALIDATED" อยู่ในส่วน Network Requests/Offers ของ dumpsys → อ่านเฉพาะ "Current Networks:" |

หลังทดสอบ: เปิด Wi-Fi คืนตามสถานะเดิมของโทรศัพท์

### Fault tests บนเครื่องจริง (G1-04 — ก่อน Submit เท่านั้น), 2026-10-07
| Test | วิธี | ผล |
|---|---|---|
| A: การเชื่อมต่อหลุดระหว่างส่งไฟล์ | `adb kill-server` 4 วินาทีหลังเริ่ม push 158 MB | Journal: TRANSFERRING → RETRYABLE_FAILED ("connection reset") — ปลอดภัย ไม่ถึง Submit |
| B: Agent crash ระหว่างส่งไฟล์ (ก่อนแก้) | kill process Agent ระหว่าง push | Journal ค้าง TRANSFERRING → `agent.cli recover` → RETRYABLE_FAILED; **พบบั๊ก**: `adb push` ที่เป็น process ลูกทำงานต่อจนเขียนไฟล์ครบ 158 MB ด้วยชื่อจริงในโฟลเดอร์ที่ Gallery index (MediaStore มี row แล้ว) โดยไม่ผ่านการตรวจ hash |
| B2: ทดสอบซ้ำหลังแก้ (staging) | เหมือน B | ไฟล์ orphan อยู่ใน `.incoming/<uuid>.part` (มี .nomedia) เท่านั้น; ไม่มีไฟล์ชื่อจริงและไม่มี row ใน MediaStore; recover → RETRYABLE_FAILED; retry ล้าง staging แล้วส่ง+ตรวจ hash+rename สำเร็จ, พบใน Gallery |
| C: Agent crash ทันทีหลังกดโพสต์ | journal SUBMITTING → กดโพสต์ → process exit ทันที → `agent.cli recover` | UNKNOWN, may_retry=false; โพสต์มีเพียง 1 รายการ; resolve ด้วยหลักฐาน → VERIFIED_SUCCESS (`docs/runbooks/tiktok-posting-poc.md`) |

