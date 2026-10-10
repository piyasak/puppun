/*
 * P6.4/G6-05 browser journey: a customer cannot see the admin area; a user made admin on the server
 * (clipflow_api.manage, never through the web) finds the customer's Workspace, extends the cycle and
 * gives quota with a reason, and the audit shows it.
 */
import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { signUpAndOnboard } from './helpers'

function grantRole(email: string, role: string) {
  execFileSync(process.env.E2E_PYTHON ?? 'python', ['-m', 'clipflow_api.manage', 'grant-role', '--email', email, '--role', role], {
    cwd: '../..', env: { ...process.env, DATABASE_URL: process.env.E2E_DATABASE_URL ?? '' },
  })
}

test('staff find a workspace and change it with an audited reason', async ({ page, browser, request }) => {
  const customer = await signUpAndOnboard(page, request)
  await expect(page.getByRole('link', { name: 'ผู้ดูแลระบบ' })).toHaveCount(0)
  await page.goto('/admin')
  await expect(page.getByText('ไม่พบหน้านี้').first()).toBeVisible()

  const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:5173', locale: 'th-TH' })
  const staffPage = await ctx.newPage()
  const staff = await signUpAndOnboard(staffPage, request)
  grantRole(staff.email, 'admin')
  await staffPage.reload()
  await staffPage.getByRole('link', { name: 'ผู้ดูแลระบบ' }).click()
  await staffPage.getByLabel('ค้นหา', { exact: true }).fill(customer.username)
  await staffPage.getByRole('button', { name: 'ค้นหา' }).first().click()
  await expect(staffPage.getByTestId('admin-ws')).toHaveCount(1)
  await staffPage.getByTestId('admin-ws').getByRole('button', { name: 'เปิด' }).click()
  const detail = staffPage.getByTestId('admin-detail')
  await expect(detail.getByTestId('admin-quota')).toHaveText('ใช้ 0 จาก 30 (เหลือ 30)')

  await expect(detail.getByRole('button', { name: 'ปรับโควตา' })).toBeDisabled()  // no reason yet
  await detail.getByLabel('จำนวนคลิป (+ คืน / − หัก)').fill('5')
  await detail.getByLabel('เหตุผล: ปรับโควตา').fill('ชดเชยงานล้มเหลวจากระบบ #E2E')
  await detail.getByRole('button', { name: 'ปรับโควตา' }).click()
  await expect(detail.getByTestId('admin-quota')).toHaveText('ใช้ 0 จาก 35 (เหลือ 35)')

  await detail.getByLabel('จำนวนวัน').fill('14')
  await detail.getByLabel('เหตุผล: ขยายรอบ').fill('ต่อให้ลูกค้าทดลองตามที่ PO อนุมัติ')
  await detail.getByRole('button', { name: 'ขยายรอบ' }).click()
  const audit = detail.getByTestId('admin-audit')
  await expect(audit).toContainText('admin.subscription.extend')
  await expect(audit).toContainText('ต่อให้ลูกค้าทดลองตามที่ PO อนุมัติ')
  await expect(audit).toContainText('admin.quota.adjust')
  await staffPage.screenshot({ path: '../../var/evidence/e2e/admin.png', fullPage: true })

  grantRole(staff.email, 'none')
  await ctx.close()
})

test('admins set a price and open or close a plan for sale themselves (PO 2026-10-10)', async ({ page, request }) => {
  const staff = await signUpAndOnboard(page, request)
  grantRole(staff.email, 'admin')
  await page.goto('/admin')
  const starter = page.getByTestId('plan-starter')
  await expect(starter).toContainText('฿200')
  await expect(starter).toContainText('เปิดขาย')
  const reason = 'ทดสอบเปิดปิดการขายจากหน้า Admin'

  // Close for sale: the public plan list (landing page, checkout) no longer offers it
  await starter.getByLabel('เหตุผล: starter').fill(reason)
  await starter.getByRole('button', { name: 'ปิดขาย' }).click()
  await expect(page.getByText('starter: ปิดขายแล้ว')).toBeVisible()
  const listed = async () => ((await (await request.get('http://127.0.0.1:8001/v1/billing/plans')).json()).items as { code: string }[]).map((p) => p.code)
  expect(await listed()).not.toContain('starter')

  // Open again, then a new price as a new version
  await page.getByTestId('plan-starter').getByLabel('เหตุผล: starter').fill(reason)
  await page.getByTestId('plan-starter').getByRole('button', { name: 'เปิดขาย (Go live)' }).click()
  await expect(page.getByText('starter: เปิดขายแล้ว')).toBeVisible()
  expect(await listed()).toContain('starter')
  const editor = page.getByTestId('plan-starter')
  await editor.getByLabel('ราคา (บาท)').fill('250')
  await editor.getByLabel('เหตุผล: starter').fill(reason)
  await editor.getByRole('button', { name: 'บันทึกราคา/สิทธิ์ (เวอร์ชันใหม่)' }).click()
  await expect(page.getByTestId('plan-starter')).toContainText('฿250')
  await page.screenshot({ path: '../../var/evidence/e2e/admin-plans.png', fullPage: true })
  // Back to the launch price for the rest of the run
  await page.getByTestId('plan-starter').getByLabel('ราคา (บาท)').fill('200')
  await page.getByTestId('plan-starter').getByLabel('เหตุผล: starter').fill(reason)
  await page.getByTestId('plan-starter').getByRole('button', { name: 'บันทึกราคา/สิทธิ์ (เวอร์ชันใหม่)' }).click()
  await expect(page.getByTestId('plan-starter')).toContainText('฿200')
})
