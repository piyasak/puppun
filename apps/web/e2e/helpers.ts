import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { randomBytes, randomUUID } from 'node:crypto'

export const API = 'http://127.0.0.1:8001'

const MAILPIT = process.env.E2E_MAILPIT_URL ?? 'http://127.0.0.1:54324'

function decodeEntities(s: string) {
  return s.replace(/&amp;/g, '&')
}

/** Waits for a new message to `email` whose body contains an auth link, returns the link. */
export async function mailLink(request: APIRequestContext, email: string, after: Set<string>, type: string) {
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

export async function messageIds(request: APIRequestContext, email: string) {
  const res = await request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:"${email}"` } })
  const { messages } = (await res.json()) as { messages: { ID: string }[] }
  return new Set(messages.map((m) => m.ID))
}

export async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('อีเมล').fill(email)
  await page.getByLabel('รหัสผ่าน', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'เข้าสู่ระบบ' }).click()
}

export function newTestUser() {
  const tag = randomBytes(5).toString('hex')
  return { tag, email: `e2e-${tag}@example.com`, password: `E2e-pass-${tag}`, username: `e2e${tag}` }
}

/** Synthetic local account: sign up, confirm through Mailpit, onboard. Ends on the dashboard. */
export async function signUpAndOnboard(page: Page, request: APIRequestContext) {
  const user = newTestUser()
  await page.goto('/signup')
  await page.getByLabel('อีเมล').fill(user.email)
  await page.getByLabel('รหัสผ่าน', { exact: true }).fill(user.password)
  await page.getByLabel('ยืนยันรหัสผ่าน').fill(user.password)
  await page.getByRole('button', { name: 'สมัครสมาชิก' }).click()
  await expect(page.getByRole('heading', { name: 'ตรวจสอบอีเมลของคุณ' })).toBeVisible()
  await page.goto(await mailLink(request, user.email, new Set(), 'signup'))
  await expect(page).toHaveURL(/\/onboarding$/)
  await page.getByLabel('ชื่อผู้ใช้').fill(user.username)
  await page.getByLabel(/ข้าพเจ้ารับรองว่ามีสิทธิ์/).check()
  await page.getByRole('button', { name: 'เริ่มใช้งาน' }).click()
  await expect(page.getByTestId('me-username')).toHaveText(user.username)
  return user
}

/** Creates an Environment + Agent token in the UI, then signs in as an Agent (API). Returns the session token. */
export async function agentSession(page: Page, request: APIRequestContext, username: string) {
  await page.getByRole('link', { name: 'Environments' }).click()
  await page.getByLabel('ชื่อ Environment').fill('หน้าร้าน')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'หน้าร้าน' })).toBeVisible()
  await page.getByRole('link', { name: 'Agent Token' }).click()
  await page.getByLabel('ชื่อ Token').fill('PC')
  await page.getByRole('button', { name: 'สร้าง Token' }).click()
  const token = await page.getByTestId('new-token').inputValue()
  await page.getByRole('button', { name: 'ฉันเก็บ Token แล้ว' }).click()
  const resp = await request.post(`${API}/v1/agent/authenticate`, {
    data: { username, token, installation_id: randomUUID() },
  })
  expect(resp.status()).toBe(200)
  return (await resp.json()).session_token as string
}
