# Stripe (D06) — ตั้งค่าการรับชำระเงิน

PO 2026-10-10: ใช้ Stripe เป็นผู้ให้บริการรับชำระเงิน ระบบใช้ **Stripe Checkout** (หน้าชำระเงินของ Stripe) แบบจ่ายทีละรอบ ไม่ต่ออายุอัตโนมัติ และไม่คืนเงิน (D06) ยอดเงินคำนวณที่ server จากแพ็กเกจเสมอ

> ห้ามใส่ key ในโค้ด แชท หรือไฟล์ที่ commit ให้ใส่ใน dashboard ของ Render เท่านั้น
> staging ใช้ได้เฉพาะ **test mode** (`sk_test_…`) เพราะ server ปฏิเสธ live key ถ้า `APP_ENV` ไม่ใช่ `production`

## 1. ใน Stripe Dashboard (test mode)

1. สมัครหรือเข้า https://dashboard.stripe.com แล้วเปิด **Test mode** มุมขวาบน
2. **Settings → Payment methods:** เปิด Cards และเปิด **PromptPay** ถ้าต้องการ (บัญชีไทย)
3. **Developers → API keys:** คัดลอก **Secret key** (`sk_test_…`) แล้วเก็บไว้ใส่ใน Render ในขั้นที่ 2 ไม่ต้องใช้ publishable key
4. **Developers → Webhooks → Add endpoint:**
   - URL: `https://punpun-staging.onrender.com/v1/billing/webhooks/stripe`
   - Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`
   - บันทึก แล้วกด **Reveal signing secret** (`whsec_…`)

## 2. ใน Render (service `punpun-staging` → Environment)

ค่าเหล่านี้จะไม่ขึ้นมาให้กรอกเอง: Render ถามค่า `sync: false` เฉพาะตอนสร้าง Blueprint ครั้งแรก ตัวที่เพิ่มใน `render.yaml` ทีหลังจะถูกข้าม ให้กด **Edit → Add Environment Variable** แล้วพิมพ์ชื่อ key เอง

| Key | ค่า |
|---|---|
| `BILLING_PROVIDER` | `stripe` |
| `STRIPE_SECRET_KEY` | `sk_test_…` จากขั้นที่ 1.3 |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` จากขั้นที่ 1.4 |

บันทึกแล้ว Render จะ deploy ใหม่เอง ถ้าตั้ง `BILLING_PROVIDER=stripe` แต่ key ไม่ครบหรือไม่ถูกต้อง หน้าแพ็กเกจจะแจ้งว่ายังชำระเงินไม่ได้ ระบบไม่ตกกลับไปใช้ sandbox

## 3. ทดสอบ (test mode ไม่มีเงินจริง)

1. Login บน staging → **แพ็กเกจ** → **ซื้อแพ็กเกจนี้** จะถูกพาไปหน้าชำระเงินของ Stripe
2. **บัตรทดสอบ:** `4242 4242 4242 4242` วันหมดอายุเป็นวันในอนาคตใดก็ได้ CVC ใดก็ได้ จ่ายแล้วจะกลับมาหน้าแพ็กเกจ และแพ็กเกจเปลี่ยนหลังได้รับ webhook ภายในไม่กี่วินาที
3. **บัตรที่ถูกปฏิเสธ:** `4000 0000 0000 0002` แพ็กเกจต้องไม่เปลี่ยน
4. **PromptPay (test):** เลือก PromptPay แล้วกด Authorize หรือ Fail ในหน้าทดสอบของ Stripe
5. ดูผล webhook ที่ Stripe → Developers → Webhooks → endpoint → **Events** ทุก event ควรได้ HTTP 200

## 4. เปิดรับเงินจริง (ยังไม่ทำ)

ต้องทำครบทุกข้อก่อน:
- G6-01 และ G6-02 ผ่าน และ PO ลงนาม G6
- ระบบ production แยกจาก staging (`APP_ENV=production`)
- ใช้ live key และ webhook ของ live mode
- เอกสารภาษีและใบเสร็จตาม D06

## ระบบทำงานอย่างไร

- `POST /v1/billing/checkout` สร้าง Payment (pending) แล้วสร้าง Checkout Session ที่ Stripe ด้วย idempotency key = payment id ได้ `checkout_url` ของ Stripe กลับมา
- Webhook ตรวจ `Stripe-Signature` บน raw body (HMAC-SHA256, คลาดเคลื่อนได้ไม่เกิน 5 นาที) ก่อน parse เสมอ
- event ซ้ำถูกนับครั้งเดียว (provider + event id), สถานะเดินหน้าอย่างเดียว, ยอดเงินและสกุลเงินต้องตรงกับ Payment ไม่อย่างนั้นจะไม่ให้สิทธิ์
- event ที่ไม่ใช้ตอบ 200 และไม่ทำอะไร เพื่อไม่ให้ Stripe ส่งซ้ำ
- โค้ด: `services/api/clipflow_api/stripe_provider.py`, `billing.py`, `routers/billing.py`
