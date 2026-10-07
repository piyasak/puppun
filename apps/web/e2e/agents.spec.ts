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

  await page.getByRole('link', { name: 'Agent Token' }).click()
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
