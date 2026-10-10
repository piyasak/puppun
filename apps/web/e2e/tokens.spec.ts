/*
 * FR-12 / FR-13 / G2-02 browser journey (local Supabase, synthetic account):
 * plan usage -> create Environment -> plan cap enforced -> create Agent token -> shown once
 * and copied -> gone after closing/reload -> rotate (new secret once, old revoked) -> revoke.
 */
import { expect, test } from '@playwright/test'
import { signUpAndOnboard } from './helpers'

const TOKEN_RE = /^cfat_[a-z0-9]{10}_[A-Za-z0-9_-]{43}$/

test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

test('environment limits and agent token lifecycle', async ({ page, request }) => {
  await signUpAndOnboard(page, request)

  // Environments: demo plan caps, allocation, cap enforcement
  await page.getByRole('link', { name: 'Environments' }).click()
  await expect(page.getByTestId('usage-registered_agent_limit')).toHaveText('0 / 2')
  await page.getByLabel('ชื่อ Environment').fill('สำนักงาน')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'สำนักงาน' })).toBeVisible()
  await expect(page.getByTestId('usage-registered_agent_limit')).toHaveText('1 / 2')

  await page.getByLabel('ชื่อ Environment').fill('บ้าน')
  await page.getByRole('spinbutton', { name: 'Agent ที่ลงทะเบียนได้', exact: true }).fill('2')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('alert')).toHaveText('เกินจำนวนที่แพ็กเกจอนุญาต เมื่อรวมกับ Environment อื่นทั้งหมด')
  await expect(page.getByTestId('usage-registered_agent_limit')).toHaveText('1 / 2')

  // Token: create, shown once, copy
  await page.getByRole('navigation', { name: 'เมนูหลัก' }).getByRole('link', { name: 'Agent Token' }).click()
  await page.getByLabel('ชื่อ Token').fill('PC หน้าร้าน')
  await page.getByRole('button', { name: 'สร้าง Token' }).click()
  const secret = page.getByTestId('new-token')
  await expect(secret).toHaveValue(TOKEN_RE)
  const token = await secret.inputValue()
  await page.getByRole('button', { name: 'คัดลอก' }).click()
  await expect(page.getByRole('button', { name: 'คัดลอกแล้ว ✓' })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(token)
  await page.screenshot({ path: '../../var/evidence/e2e/token-shown-once.png', fullPage: true })

  await page.getByRole('button', { name: 'ฉันเก็บ Token แล้ว' }).click()
  await expect(page.getByTestId('new-token')).toHaveCount(0)
  const row = page.getByTestId('token-row').filter({ hasText: 'PC หน้าร้าน' })
  await expect(row).toContainText('ใช้งานได้')
  await page.reload()
  await expect(page.getByTestId('token-row')).toHaveCount(1)
  expect(await page.content()).not.toContain(token.slice(16)) // the secret never comes back

  // Rotate: confirm dialog, new token once, old one revoked
  await page.getByRole('button', { name: 'Rotate' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('ยกเลิก Token เดิมทันที')
  await dialog.getByRole('button', { name: 'Rotate' }).click()
  await expect(page.getByTestId('new-token')).toHaveValue(TOKEN_RE)
  const rotated = await page.getByTestId('new-token').inputValue()
  expect(rotated).not.toBe(token)
  await page.getByRole('button', { name: 'ฉันเก็บ Token แล้ว' }).click()
  await expect(page.getByTestId('token-row')).toHaveCount(2)
  await expect(page.getByTestId('token-row').filter({ hasText: 'ยกเลิกแล้ว' })).toHaveCount(1)

  // Revoke: cancel first, then confirm
  await page.getByRole('button', { name: 'ยกเลิก Token' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิก', exact: true }).click()
  await expect(page.getByTestId('token-row').filter({ hasText: 'ใช้งานได้' })).toHaveCount(1)
  await page.getByRole('button', { name: 'ยกเลิก Token' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิก Token' }).click()
  await expect(page.getByTestId('token-row').filter({ hasText: 'ยกเลิกแล้ว' })).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Rotate' })).toHaveCount(0)
  await page.screenshot({ path: '../../var/evidence/e2e/tokens-revoked.png', fullPage: true })
})
