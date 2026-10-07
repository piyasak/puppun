# ClipFlow

บริการสมาชิกรายเดือน: รับลิงก์ YouTube/Bilibili ที่ผู้ใช้มีสิทธิ์ → ผลิตคลิปแนวตั้งหลายคลิป → สร้าง Title/Ending/Caption/Hashtag ที่แก้ไขได้ → ตั้งโพสต์ทุก X ชั่วโมงไปยังโทรศัพท์ Android ผ่าน Windows Agent ของลูกค้า

**สถานะ: Phase 0 (เอกสารและ Gate register) — ยังไม่มีระบบที่ใช้งานได้ ยังไม่มี Gate ใดผ่าน**

## เอกสาร
| ไฟล์ | เนื้อหา |
|---|---|
| `PRD_CLAUDE_CODE.md` | PRD และสัญญาการพัฒนา (แหล่งอ้างอิงหลัก) |
| `docs/progress.md` | สถานะล่าสุด / งานถัดไป (อ่านก่อนเริ่มงาน) |
| `docs/architecture.md` | Components, identity/permission model, state machines |
| `docs/decisions.md` | D01–D07, คำถามที่รอ PO (Q-xx), engineering decisions (E-xx) |
| `docs/requirements-map.md` | FR/NF → module → test → gate |
| `docs/ui-map.md` | Routes, journeys, สถานะของทุกหน้าจอ |
| `docs/backlog.md` | Backlog ตาม Phase + แผนทรัพยากร/fixture/อุปกรณ์ |
| `docs/compatibility.md` | เครื่องมือและเมทริกซ์ที่ตรวจแล้ว |
| `docs/gates/G0.md … G8.md` | Gate records (47 checks) |

## คำสั่ง
บน Windows ที่ไม่มี `make` ให้ใช้ `py tasks.py <target>` (เทียบเท่า `make <target>`)

```bash
py tasks.py test-unit          # unit tests (ตอนนี้: เครื่องมือ check-gate)
py tasks.py check-gate 0       # ตรวจ gate record; exit 0=ผ่าน, 1=ยังไม่ผ่าน, 2=record ไม่ถูกต้อง
py -m pytest tests/unit/test_check_gate.py::test_fully_supported_gate_passes   # รันเทสเดียว
```

Target อื่น (`setup`, `dev`, `migrate`, `lint`, `typecheck`, `build`, …) ยังไม่ได้สร้าง และจะ exit 3 พร้อมระบุ Phase ที่จะสร้าง

ค่าเริ่มต้นความปลอดภัย: `APP_ENV=development`, `POSTING_MODE=dry_run`, `BILLING_PROVIDER=sandbox` (ดู `.env.example`)
