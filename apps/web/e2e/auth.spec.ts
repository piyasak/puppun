/*
 * FR-01 / G2-01 browser journey on LOCAL Supabase + Mailpit (synthetic accounts only):
 * sign up -> blocked until confirmed -> confirm link -> onboarding -> dashboard -> sign out
 * -> generic login errors -> reset without enumeration -> new password works, old does not.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { randomBytes } from 'node:crypto'

const MAILPIT = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:54324'

function decodeEntities(s: string) {
  return s.replace(/&amp;/g, '&')
}

/** Waits for a new message to `email` whose body contains an auth link, returns the link. */
async function mailLink(request: APIRequestContext, email: string, after: Set<string>, type: string) {
  for (let i = 0; i < 40; i++) {
    const res = await request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:"${email}"` } })
    const { messages } = (await res.json()) as { messages: { ID: string }[] }
    for (const m of messages.filter((m) => !after.has(m.ID))) {
      const body = await (await request.get(`${MAILPIT}/api/v1/message/${m.ID}`)).json()
      const text = `${body.Text ?? ''}\n${body.HTML ?? ''}`
      const link = text.match(new RegExp(`https?://[^\\s"'<>]+/auth/v1/verify\\?[^\\s"'<>]*type=${type}[^\\s"'<>]*`))
      if (link) {
        after.add(m.ID)
        return decodeEntities(link[0])
      }
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`no ${type} email for ${email}`)
}

async function messageIds(request: APIRequestContext, email: string) {
  const res = await request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:"${email}"` } })
  const { messages } = (await res.json()) as { messages: { ID: string }[] }
  return new Set(messages.map((m) => m.ID))
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('อีเมล').fill(email)
  await page.getByLabel('รหัสผ่าน', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'เข้าสู่ระบบ' }).click()
}

test('sign up, confirm, onboard, reset password', async ({ page, request }) => {
  const tag = randomBytes(5).toString('hex')
  const email = `e2e-${tag}@example.com`
  const password = `E2e-pass-${tag}`
  const newPassword = `E2e-new-${tag}`
  const seen = new Set<string>()

  // Sign up
  await page.goto('/signup')
  await page.getByLabel('อีเมล').fill(email)
  await page.getByLabel('รหัสผ่าน', { exact: true }).fill(password)
  await page.getByLabel('ยืนยันรหัสผ่าน').fill(password)
  await page.getByRole('button', { name: 'สมัครสมาชิก' }).click()
  await expect(page.getByRole('heading', { name: 'ตรวจสอบอีเมลของคุณ' })).toBeVisible()

  // Not usable before the email is confirmed
  await login(page, email, password)
  await expect(page.getByRole('alert')).toHaveText('กรุณายืนยันอีเมลก่อน โดยกดลิงก์ในอีเมลที่เราส่งให้')

  // Confirm -> signed in -> must finish onboarding first
  await page.goto(await mailLink(request, email, seen, 'signup'))
  await expect(page).toHaveURL(/\/onboarding$/)
  await page.getByLabel('ชื่อผู้ใช้').fill(`e2e${tag}`)
  await page.getByRole('button', { name: 'เริ่มใช้งาน' }).click()
  await expect(page.getByRole('alert')).toHaveText('กรุณายอมรับคำรับรองสิทธิ์ในเนื้อหา')
  await page.getByLabel(/ข้าพเจ้ารับรองว่ามีสิทธิ์/).check()
  await page.getByRole('button', { name: 'เริ่มใช้งาน' }).click()

  // Dashboard shows data that came from the ClipFlow API (/v1/me)
  await expect(page.getByTestId('me-username')).toHaveText(`e2e${tag}`)
  await expect(page.getByTestId('me-email')).toHaveText(email)
  await expect(page.getByText(/ยอมรับแล้ว \(ฉบับ/)).toBeVisible()
  await page.screenshot({ path: '../../var/evidence/e2e/dashboard.png', fullPage: true })

  // Sign out
  await page.getByRole('button', { name: 'ออกจากระบบ' }).click()
  await expect(page).toHaveURL(/\/login$/)

  // Wrong password and unknown account give the same message
  await login(page, email, 'wrong-password-123')
  const wrong = await page.getByRole('alert').textContent()
  await login(page, `nobody-${tag}@example.com`, 'wrong-password-123')
  await expect(page.getByRole('alert')).toHaveText(wrong ?? '')

  // Reset: same answer for a missing account, and no email is sent to it
  const ghost = `ghost-${tag}@example.com`
  for (const target of [ghost, email]) {
    await page.goto('/forgot')
    await page.getByLabel('อีเมล').fill(target)
    await page.getByRole('button', { name: 'ส่งลิงก์ตั้งรหัสผ่านใหม่' }).click()
    await expect(page.getByRole('status')).toHaveText('หากอีเมลนี้มีบัญชีอยู่ เราได้ส่งลิงก์ตั้งรหัสผ่านใหม่ไปแล้ว')
  }
  const resetLink = await mailLink(request, email, seen, 'recovery')
  expect((await messageIds(request, ghost)).size).toBe(0)

  await page.goto(resetLink)
  await expect(page).toHaveURL(/\/reset#?$/)
  await page.getByLabel('รหัสผ่านใหม่', { exact: true }).fill(newPassword)
  await page.getByLabel('ยืนยันรหัสผ่านใหม่').fill(newPassword)
  await page.getByRole('button', { name: 'บันทึกรหัสผ่านใหม่' }).click()
  await expect(page).toHaveURL(/\/login\?reset=1$/)

  // Old password no longer works; new one does
  await login(page, email, password)
  await expect(page.getByRole('alert')).toHaveText('อีเมลหรือรหัสผ่านไม่ถูกต้อง')
  await login(page, email, newPassword)
  await expect(page.getByTestId('me-username')).toHaveText(`e2e${tag}`)

  // A used reset link cannot be used again
  await page.getByRole('button', { name: 'ออกจากระบบ' }).click()
  await page.goto(resetLink)
  await expect(page.getByRole('heading', { name: 'ลิงก์ไม่ถูกต้องหรือหมดอายุ' })).toBeVisible()
})

test('dashboard requires a session', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
