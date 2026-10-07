# UI map — routes, journeys, states (P0.4 / G0-02)

ไม่มี UI ต้นแบบใน repository (Q-09) — แผนผังนี้ยึด Screen coverage ใน PRD §L และ §O.3
หลักการ: UI ไทย, คำเรียกตาม Glossary ด้านล่าง, Sidebar บน Desktop / เมนูล่าง+Drawer บน Mobile (≥360px), สีหลักน้ำเงิน, สถานะมีข้อความเสมอ (ไม่ใช้สีอย่างเดียว)

## Glossary (ใช้คำเดียวกันทุกหน้า)

| คำในระบบ | คำบน UI |
|---|---|
| Workspace | พื้นที่ทำงาน |
| Job | งานผลิตคลิป |
| Clip | คลิป |
| Source | ต้นฉบับ |
| Schedule series / item | ตารางโพสต์ / รอบโพสต์ |
| Environment | สภาพแวดล้อม (Environment) |
| Agent Token | โทเคน Agent |
| Agent installation / session | เครื่องที่ติดตั้ง Agent / การเชื่อมต่อ |
| Device | โทรศัพท์ |
| Expected account | บัญชี TikTok ปลายทาง |
| UNKNOWN | ผลไม่ชัดเจน — ต้องตรวจสอบ |
| NEEDS_ACTION | ต้องดำเนินการ |
| Approve | อนุมัติคลิป |
| Quota | โควตา |

## Routes

สถานะมาตรฐาน: **L** Loading • **E** Empty • **V** Validation error • **P** Permission denied/404 • **X** Server/Network error • **S** Success • **D** Disabled (พร้อมเหตุผล)

| Route | หน้าจอ | Journey | สถานะที่ต้องมี | API หลัก | FR | Phase |
|---|---|---|---|---|---|---|
| /signup | สมัครสมาชิก | เริ่มสมาชิก | V, X, S | POST /auth/register | FR-01 | P2 |
| /login | เข้าสู่ระบบ | — | V, X, S | POST /auth/login | FR-01 | P2 |
| /reset, /reset/confirm | กู้รหัสผ่าน | — | V, X, S (ข้อความเดียวกันไม่ว่ามีบัญชีหรือไม่) | /auth/password-reset/* | FR-01 | P2 |
| / | Dashboard: แพ็กเกจ วันหมดอายุ โควตา งานล่าสุด เครื่องพร้อม/ไม่พร้อม รอบโพสต์ถัดไป รายการต้องดำเนินการ | ทุก Journey | L, E (ยังไม่มีงาน → CTA สร้างงาน; ยังไม่มีเครื่อง → CTA เชื่อมเครื่อง), X | GET /me, /workspace/usage | FR-01,21 | P2 |
| /create (4 ขั้น) | 1 ต้นฉบับ: เลือก "ลิงก์ YouTube/Bilibili" หรือ "ไฟล์บนเครื่อง Agent" (Q-17 — รายการไฟล์ที่ Agent รายงาน ไม่อัปโหลดไฟล์ต้นฉบับขึ้นเว็บ); ข้อตกลงสิทธิ์ยอมรับครั้งเดียวตอนสมัคร (Q-14) → 2 รูปแบบ (จำนวนคลิป ความยาว Template โหมด Review/Auto) → 3 เครื่อง/เวลา (preview จาก Server) → 4 ตรวจและสร้าง (แสดงโควตาที่จะใช้) | ผลิตคลิป | L, V (inline ต่อช่อง), D (ไม่มีเครื่อง/โควตาไม่พอ + เหตุผล), X, S → ไป Job detail | POST /jobs, POST /schedules/preview | FR-02,05,08,09,10 | P3/P4 |
| /jobs | รายการงาน แท็บ: ทั้งหมด/กำลังผลิต/รอตรวจ/พร้อมโพสต์/ต้องดำเนินการ/ล้มเหลว | ตรวจคลิป | L, E ต่อแท็บ, X | GET /jobs | FR-03 | P3 |
| /jobs/:id | รายละเอียดงาน: สถานะ timeline, ต้นฉบับ, คลิป (Preview จริง), ช่วงต้นฉบับ, ข้อความแก้ไขได้, อนุมัติ, ยกเลิก | ตรวจคลิป | L, P, X, V (ข้อความ), S, D (อนุมัติไม่ได้เพราะ render ไม่ตรง version), สถานะ "ข้อความเปลี่ยน ต้อง Render ใหม่" | GET /jobs/:id, PATCH /clips/:id/metadata, POST /clips/:id/approve, GET /clips/:id/media, POST /jobs/:id/cancel | FR-04..08,19 | P3 |
| /schedule | ตารางโพสต์ มุมมองสัปดาห์/รายการ | เผยแพร่ | L, E, X | GET /schedules | FR-09..11 | P4 |
| /schedule/items/:id | รายละเอียดรอบโพสต์: เวลานัด/Claim/เริ่ม/Submit/ยืนยัน แยกกัน, เหตุผลเมื่อเลื่อน/ข้าม, Collision | เผยแพร่ | L, P, X, D (แก้ไม่ได้เพราะ Claim แล้ว) | PATCH /schedule-items/:id, POST …/cancel | FR-11,19 | P4 |
| /schedule/:seriesId | Series: pause/resume (แสดง preview ใหม่ก่อนยืนยัน), ยกเลิก | เผยแพร่ | L, X, S, ยืนยันก่อนยกเลิก | /schedules/:id/pause,/resume | FR-19 | P4 |
| /attempts/:id/resolve | แก้ผลไม่ชัดเจน: หลักฐาน + ตัวเลือก (พบโพสต์ / ยืนยันว่าไม่ได้โพสต์ / ยังไม่ทราบ) — ไม่มีตัวเลือกที่เลือกไว้ล่วงหน้า | จัดการปัญหา | L, V (ต้องแนบหลักฐาน), X, S | POST /publish-attempts/:id/resolve | FR-18 | P5 |
| /devices | รายการโทรศัพท์: สถานะพร้อม/Offline/unauthorized/ผิดบัญชี พร้อมเหตุผล | เชื่อมเครื่อง | L, E (CTA ติดตั้ง Agent), X | GET /devices | FR-15 | P2 |
| /devices/:id | รายละเอียด: rename, บัญชีปลายทาง, งานค้าง, ถอดการผูก (ยืนยัน + แสดงงานที่ได้รับผล) | เชื่อมเครื่อง | L, P, V, X, S, D (Unbind ระหว่าง Submit) | PATCH /devices/:id, POST …/unbind | FR-15,16 | P2 |
| /connection | การเชื่อมต่อ: ขั้นตอน 1 สร้าง Environment → 2 สร้างโทเคน → 3 ดาวน์โหลด/ตั้งค่า Agent → 4 ลงทะเบียนเครื่อง | เชื่อมเครื่อง | L, E, X | — | FR-12..15 | P2 |
| /environments, /environments/:id | Environment + ขีดจำกัด (ทะเบียน Agent, Session พร้อมกัน, เครื่อง) แสดงยอดรวมเทียบแพ็กเกจ | เชื่อมเครื่อง | L, E, V (เกินแพ็กเกจ), X, S | /environments | FR-13 | P2 |
| /tokens | โทเคน: สร้าง (แสดงเต็มครั้งเดียว + ปุ่มคัดลอก + เตือนว่าจะไม่แสดงอีก), รายการแสดงเฉพาะ prefix, Revoke/Rotate (ยืนยัน) | เชื่อมเครื่อง | L, E, X, S | /agent-tokens | FR-12 | P2 |
| /agents | เครื่องที่ติดตั้ง Agent + การเชื่อมต่อ: last heartbeat, version, ยกเลิกทะเบียน, ตัด Session | เชื่อมเครื่อง | L, E, X, S | (P2 endpoint ใหม่ — เพิ่มใน contract) | FR-13,14 | P2 |
| /templates, /templates/:id | Template ข้อความ/รูปแบบ มี version | ผลิตคลิป | L, E, V, X, S | /templates | FR-07 | P3 |
| /billing | แพ็กเกจ (ราคาที่ยังไม่อนุมัติมีป้าย "ตัวอย่าง"), checkout, รอชำระ, ประวัติ | เริ่มสมาชิก | L, E, X, S, Pending | /billing/* | FR-20 | P6 |
| /settings | โปรไฟล์ timezone รหัสผ่าน การแจ้งเตือน | — | L, V, X, S | /me | FR-01 | P2 |
| /notifications | งานผิดพลาด เครื่อง Offline ผลไม่ชัดเจน สมาชิกหมดอายุ พร้อมลิงก์ไปหน้าที่แก้ | จัดการปัญหา | L, E, X | (P6) | FR-23 | P6 |
| /support | ติดต่อ Support อ้างอิง Job ID | จัดการปัญหา | V, X, S | (P6) | FR-23 | P6 |
| /admin/users, /admin/plans, /admin/jobs, /admin/payments | Admin (ต้องมีสิทธิ์ admin; ทุกการแก้ต้องใส่เหตุผล) | ดูแลบริการ | L, E, P, V, X, S | /admin/* | FR-22 | P6 |

## Windows Agent surfaces (local UI)

| Surface | เนื้อหา | สถานะ |
|---|---|---|
| ไฟล์ต้นฉบับ (Q-17) | เลือกไฟล์วิดีโอ (+ .srt ถ้ามี) บนเครื่องนี้ให้เว็บเห็นเป็นต้นฉบับ; แสดงผลตรวจไฟล์ (ไม่ใช่วิดีโอ / ใหญ่เกิน / ยาวเกิน) | V, X, S |
| การผลิตคลิป (Q-15) | งานที่ Agent กำลังดาวน์โหลด/วิเคราะห์/render/อัปโหลด พร้อมความคืบหน้า; สถานะ "YouTube พักชั่วคราว ถึง HH:MM" เมื่อเจอ bot check (R-01) | L, X, D (cool-down) |
| ตั้งค่า | Server URL, Username, Token (เก็บใน Credential Manager, ไม่แสดงซ้ำ), installation_id (อ่านอย่างเดียว) | V, X (เชื่อมต่อไม่ได้ + เหตุผล), S |
| การเชื่อมต่อ | Session, Environment (จาก Server), heartbeat ล่าสุด, เวอร์ชัน | Online/Stale/Revoked |
| โทรศัพท์ | Serial ที่เห็นผ่าน ADB, unauthorized/offline, ลงทะเบียน | E (ไม่พบเครื่อง + วิธีเปิด USB debugging) |
| งาน | งานปัจจุบัน/คิว และสถานะ attempt | — |
| ต้องดำเนินการ | ผิดบัญชี, Login wall, CAPTCHA, UI ไม่รู้จัก, UNKNOWN | — |
| Activity log | Log ท้องถิ่น (redact token) | — |

## ช่องว่างที่พบ
- PRD §E ไม่มี endpoint สำหรับ "Agent list/session management" (§L ต้องมีหน้าจอ) → เพิ่ม `GET /v1/agents`, `POST /v1/agents/{id}/deregister`, `POST /v1/agent-sessions/{id}/terminate` ใน P2 (บันทึกเป็น contract addition ไม่เปลี่ยนกติกา)
- Notifications/Support ไม่มี endpoint ใน §E → กำหนดใน P6
