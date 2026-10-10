/*
 * FR-14 / G2-03 browser journey (local stack): an Agent signs in with username + token,
 * shows as online, reconnects without a second registration, is deregistered from the web,
 * and its session is refused afterwards.
 */
import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { signUpAndOnboard } from './helpers'

const API = 'http://127.0.0.1:8001'

test('agent registration, presence and deregistration', async ({ page, request }) => {
  const user = await signUpAndOnboard(page, request)

  await page.getByRole('link', { name: 'Environments' }).click()
  await page.getByLabel('ชื่อ Environment').fill('สำนักงาน')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'สำนักงาน' })).toBeVisible()

  await page.getByRole('navigation', { name: 'เมนูหลัก' }).getByRole('link', { name: 'Agent Token' }).click()
  await page.getByLabel('ชื่อ Token').fill('PC หน้าร้าน')
  await page.getByRole('button', { name: 'สร้าง Token' }).click()
  const token = await page.getByTestId('new-token').inputValue()
  await page.getByRole('button', { name: 'ฉันเก็บ Token แล้ว' }).click()

  // The Agent (simulated over HTTP) signs in twice with the same installation_id.
  const installationId = randomUUID()
  const auth = () => request.post(`${API}/v1/agent/authenticate`, {
    data: { username: user.username, token, installation_id: installationId, agent_version: '0.1.0',
            environment: 'not-trusted' },
  })
  expect((await auth()).status()).toBe(200)
  const second = await auth()
  expect(second.status()).toBe(200)
  const session = (await second.json()).session_token as string

  await page.getByRole('link', { name: 'Agent', exact: true }).click()
  const rows = page.getByTestId('agent-row')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('ออนไลน์')
  await expect(rows.first()).toContainText(installationId.slice(0, 8))

  await page.getByRole('link', { name: 'Environments' }).click()
  await expect(page.getByTestId('inuse-registered_agent_limit')).toHaveText('ใช้อยู่ 1')

  await page.getByRole('link', { name: 'Agent', exact: true }).click()
  await page.getByRole('button', { name: 'ยกเลิกทะเบียน' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิกทะเบียน' }).click()
  await expect(rows.first()).toContainText('ยกเลิกทะเบียนแล้ว')
  await page.screenshot({ path: '../../var/evidence/e2e/agents-deregistered.png', fullPage: true })

  const hb = await request.post(`${API}/v1/agent/heartbeat`, {
    data: { generation: 2 }, headers: { Authorization: `Bearer ${session}` },
  })
  expect(hb.status()).toBe(401)
  expect((await hb.json()).details.reason).toBe('deregistered')
})

test('agents page offers the double-click setup with its SHA-256 (E-50)', async ({ page, request }) => {
  const user = await signUpAndOnboard(page, request)
  await page.getByRole('link', { name: 'Agent', exact: true }).click()
  const install = page.getByTestId('agent-install')
  // The local API has no setup configured: no dead link, a way to get it instead.
  await expect(install.getByText('ยังไม่เปิดให้ดาวน์โหลด')).toBeVisible()
  await expect(install.getByRole('link', { name: /ดาวน์โหลด Agent/ })).toHaveCount(0)
  await expect(install.getByText(user.username)).toBeVisible()

  const sha = 'a'.repeat(64)
  await page.route(`${API}/v1/agents/download`, (route) => route.fulfill({
    json: { available: true, version: '0.3.0', url: 'https://downloads.example.com/punpun-agent-setup-0.3.0.exe',
            sha256: sha, size_mb: 34.9 },
  }))
  await page.reload()
  const link = install.getByRole('link', { name: 'ดาวน์โหลด Agent 0.3.0 (34.9 MB)' })
  await expect(link).toHaveAttribute('href', 'https://downloads.example.com/punpun-agent-setup-0.3.0.exe')
  await expect(install.getByTestId('setup-sha256')).toHaveText(sha)
  await page.screenshot({ path: '../../var/evidence/e2e/agents-download.png', fullPage: true })
})

test('a pairing code links a PC without copying a token (PO 2026-10-10)', async ({ page, request }) => {
  const user = await signUpAndOnboard(page, request)
  await page.getByRole('link', { name: 'Environments' }).click()
  await page.getByLabel('ชื่อ Environment').fill('ร้านหลัก')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'ร้านหลัก' })).toBeVisible()
  await page.getByRole('link', { name: 'Agent', exact: true }).click()

  await page.getByRole('button', { name: 'สร้างรหัสเชื่อมต่อ' }).click()
  const code = (await page.getByTestId('pairing-code').textContent())!.trim()
  expect(code).toMatch(/^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/)
  await expect(page.getByTestId('pairing')).toContainText('Environment ร้านหลัก')

  // What the Agent's settings window sends: the code once, then it holds its own token
  const paired = await request.post(`${API}/v1/agent/pair`, { data: { code, computer_name: 'SHOP-PC' } })
  expect(paired.status()).toBe(200)
  const body = await paired.json()
  expect(body.username).toBe(user.username)
  const auth = await request.post(`${API}/v1/agent/authenticate`, {
    data: { username: body.username, token: body.token, installation_id: randomUUID(), agent_version: '0.3.2' },
  })
  expect(auth.status()).toBe(200)
  expect((await request.post(`${API}/v1/agent/pair`, { data: { code } })).status()).toBe(400)  // once only
  // the sidebar link (the page also links to Agent Token for advanced users)
  await page.getByRole('navigation', { name: 'เมนูหลัก' }).getByRole('link', { name: 'Agent Token' }).click()
  await expect(page.getByText('PC SHOP-PC')).toBeVisible()
  await page.getByRole('link', { name: 'Agent', exact: true }).click()
  await page.screenshot({ path: '../../var/evidence/e2e/agents-pairing.png', fullPage: true })
})
