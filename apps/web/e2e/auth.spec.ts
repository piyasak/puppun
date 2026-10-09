/*
 * FR-01 / G2-01 browser journey on LOCAL Supabase + Mailpit (synthetic accounts only):
 * sign up -> blocked until confirmed -> confirm link -> onboarding -> dashboard -> sign out
 * -> generic login errors -> reset without enumeration -> new password works, old does not.
 * E-28: links open our /auth/confirm page; a mail scanner fetching the link first does not use it up.
 */
import { expect, test } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { login, mailLink, messageIds } from './helpers'

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

  // A mail scanner opens the link first (Microsoft 365 Safe Links did, 2026-10-07): nothing is used up
  const confirmLink = await mailLink(request, email, seen, 'email')
  expect((await request.get(confirmLink)).ok()).toBe(true)
  await page.goto(confirmLink)
  await page.goto(confirmLink)  // opening it twice is still fine
  // Confirm (the person presses the button) -> signed in -> must finish onboarding first
  await page.getByRole('button', { name: 'ยืนยันอีเมล' }).click()
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

  expect((await request.get(resetLink)).ok()).toBe(true)  // the scanner again
  await page.goto(resetLink)
  await page.getByRole('button', { name: 'ตั้งรหัสผ่านใหม่' }).click()
  await expect(page).toHaveURL(/\/reset$/)
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
  await page.getByRole('button', { name: 'ตั้งรหัสผ่านใหม่' }).click()
  await expect(page.getByRole('heading', { name: 'ลิงก์ไม่ถูกต้องหรือหมดอายุ' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'ขอลิงก์ใหม่' })).toBeVisible()
})

test('dashboard requires a session', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
