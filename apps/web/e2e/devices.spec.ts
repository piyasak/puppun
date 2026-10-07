/*
 * FR-15 / G2-04 browser journey (local stack, synthetic serial): an Agent registers a ready
 * phone, the web shows it, the owner sets the expected TikTok account, a second Workspace
 * cannot take the phone, and unbinding releases it.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { signUpAndOnboard } from './helpers'

const API = 'http://127.0.0.1:8001'

async function agentSession(page: Page, request: APIRequestContext, username: string) {
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

function registerPhone(request: APIRequestContext, session: string, serial: string, state = 'device') {
  return request.post(`${API}/v1/agent/devices/register`, {
    headers: { Authorization: `Bearer ${session}` },
    data: { serial, adb_state: state, model: '25078PC3EG', android_version: '15' },
  })
}

test('register, edit, protect and unbind a phone', async ({ page, browser, request }) => {
  const serial = `E2E${randomUUID().slice(0, 12).toUpperCase().replace(/-/g, '')}`
  const owner = await signUpAndOnboard(page, request)
  const session = await agentSession(page, request, owner.username)

  expect((await registerPhone(request, session, serial, 'unauthorized')).status()).toBe(409)
  const registered = await registerPhone(request, session, serial)
  expect(registered.status()).toBe(200)
  const { details_url: detailsUrl, missing_details: missing } = await registered.json()
  expect(missing).toEqual(['display_name', 'expected_account'])

  await page.getByRole('link', { name: 'โทรศัพท์' }).click()
  const row = page.getByTestId('device-row')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('พร้อมใช้งาน')
  await expect(row).toContainText(serial)
  await expect(row.getByTestId('needs-details')).toHaveText('ต้องใส่รายละเอียด: ชื่อเรียกเครื่อง, บัญชี TikTok')

  // The link the Agent prints (Q-25) opens this phone's form directly.
  await page.goto(new URL(detailsUrl).pathname + new URL(detailsUrl).search)
  await expect(page.getByLabel('บัญชี TikTok ที่ต้องโพสต์')).toBeVisible()
  await expect(page).toHaveURL(/\/devices$/)
  await page.getByLabel('ชื่อเรียกเครื่อง').fill('POCO หน้าร้าน')
  await page.getByLabel('บัญชี TikTok ที่ต้องโพสต์').fill('@Shop.Test_1')
  await page.getByRole('button', { name: 'บันทึก' }).click()
  await expect(row).toContainText('POCO หน้าร้าน')
  await expect(row).toContainText('บัญชี TikTok: @shop.test_1')
  await expect(row.getByTestId('needs-details')).toHaveCount(0)
  await page.screenshot({ path: '../../var/evidence/e2e/devices.png', fullPage: true })

  // Agent reports the phone as unauthorized -> web shows the fix
  await request.post(`${API}/v1/agent/devices/report`, {
    headers: { Authorization: `Bearer ${session}` }, data: { devices: { [serial]: 'unauthorized' } },
  })
  await page.reload()
  await expect(row).toContainText('ยังไม่อนุญาต USB debugging')
  await expect(row).toContainText('กด "อนุญาต"')

  // A second Workspace cannot bind the same phone
  const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:5173', locale: 'th-TH' })
  const otherPage = await ctx.newPage()
  const other = await signUpAndOnboard(otherPage, request)
  const otherSession = await agentSession(otherPage, request, other.username)
  const stolen = await registerPhone(request, otherSession, serial)
  expect(stolen.status()).toBe(409)
  expect((await stolen.json()).code).toBe('DEVICE_OWNERSHIP_CONFLICT')

  // Unbind (with confirmation) releases it to the other Workspace
  await row.getByRole('button', { name: 'ยกเลิกการผูก' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิกการผูก' }).click()
  await expect(row).toContainText('ยกเลิกการผูกแล้ว')
  expect((await registerPhone(request, otherSession, serial)).status()).toBe(200)
  await otherPage.getByRole('link', { name: 'โทรศัพท์' }).click()
  await expect(otherPage.getByTestId('device-row')).toContainText(serial)
  await ctx.close()
})
