/*
 * P6 (sandbox) browser journey, G6-02: trial -> buy Pro -> the sandbox provider fails -> nothing
 * changes -> buy again -> success -> the plan and quota change only once the server has the
 * verified event. Prices are examples (D05); no money moves.
 */
import { expect, test } from '@playwright/test'
import { signUpAndOnboard } from './helpers'

test('buy a plan through the sandbox provider: fail, then succeed', async ({ page, request }) => {
  await signUpAndOnboard(page, request)
  await page.getByRole('link', { name: 'แพ็กเกจ' }).click()
  const sub = page.getByTestId('subscription')
  await expect(sub).toContainText('ทดลองใช้')
  await expect(page.getByText('ราคาเป็นตัวอย่าง', { exact: false }).first()).toBeVisible()

  await page.getByTestId('plan-pro').getByRole('button').click()
  await expect(page).toHaveURL(/\/billing\/sandbox\/[0-9a-f-]{36}$/)
  await expect(page.getByTestId('pay-amount')).toHaveText('฿990')
  await page.getByRole('button', { name: 'จำลอง: ชำระไม่สำเร็จ' }).click()
  await expect(page.getByText('ชำระเงินไม่สำเร็จ ไม่มีการเปลี่ยนแพ็กเกจ')).toBeVisible()
  await expect(sub).toContainText('ทดลองใช้')

  await page.getByTestId('plan-pro').getByRole('button').click()
  await page.getByRole('button', { name: 'จำลอง: ชำระสำเร็จ' }).click()
  await expect(page.getByText('ชำระเงินสำเร็จ', { exact: false })).toBeVisible()
  await expect(sub).toContainText('ใช้งานอยู่')
  await expect(sub).toContainText('Pro')
  await expect(page.getByTestId('quota')).toHaveText('ใช้ 0 จาก 150 (เหลือ 150)')
  const rows = page.getByTestId('payment-row')
  await expect(rows).toHaveCount(2)
  await expect(rows.first()).toContainText('ชำระแล้ว')
  await expect(rows.nth(1)).toContainText('ไม่สำเร็จ')
  await page.screenshot({ path: '../../var/evidence/e2e/billing.png', fullPage: true })
})
