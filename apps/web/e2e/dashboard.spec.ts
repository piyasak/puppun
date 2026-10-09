/*
 * E-47 step 3: the dashboard shows the next post (server times, Bangkok), the quota, ready phones,
 * posts waiting for a person and recent jobs, from a real account with one scheduled post.
 */
import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { FakeAgent, sampleClip } from './agentSim'
import { agentSession, signUpAndOnboard } from './helpers'

test('dashboard shows the next post, quota, phones and recent jobs', async ({ page, request }) => {
  test.setTimeout(120_000)
  const owner = await signUpAndOnboard(page, request)

  // Empty account: every card says what to do next instead of showing zeros
  await expect(page.getByText('ยังไม่มีโพสต์ที่ตั้งเวลาไว้ใน 14 วันข้างหน้า')).toBeVisible()
  await expect(page.getByText('ยังไม่มีโทรศัพท์')).toBeVisible()
  await expect(page.getByRole('link', { name: 'สร้างงานแรก' })).toBeVisible()
  await expect(page.getByTestId('dash-quota')).toContainText('0')

  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  const phoneId = await agent.registerPhone(`DSH${randomUUID().slice(0, 8).toUpperCase()}`)
  await page.goto(`/devices?edit=${phoneId}`)
  await page.getByLabel('ชื่อเรียกเครื่อง').fill('POCO หน้าร้าน')
  await page.getByLabel('บัญชี TikTok ที่ต้องโพสต์').fill('@shop1')
  await page.getByRole('button', { name: 'บันทึก' }).click()
  await expect(page.getByTestId('device-row')).toContainText('@shop1')

  await page.goto('/create')
  await page.getByLabel('ไฟล์วิดีโอบนเครื่อง Agent').check()
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ตอนพิเศษ.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByLabel('ความยาวต่อคลิป').fill('40')  // clips of 32–40 s (the sample clips are 35 s)
  await page.getByLabel('กำหนดเอง').check()
  await page.getByLabel('จำนวนคลิป').fill('1')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  const jobId = page.url().split('/').pop()!
  expect((await agent.claim()).id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 600, possible_clips: 1 })
  await agent.event(jobId, 'stage', { stage: 'RENDERING' })
  await agent.deliver(jobId, 1, sampleClip(35), 35_000)
  await agent.event(jobId, 'completed')
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })
  await page.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 1)' }).click()
  const panel = page.getByRole('region', { name: 'ตั้งเวลาโพสต์' })
  const tomorrow = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(new Date(Date.now() + 864e5))
  await panel.getByLabel('เริ่ม (เวลาประเทศไทย)').fill(`${tomorrow}T19:00`)
  await panel.getByRole('button', { name: 'ดูตัวอย่างเวลา' }).click()
  await panel.getByRole('button', { name: 'ยืนยันตั้งเวลา 1 โพสต์' }).click()
  await expect(panel.getByTestId('schedule-item')).toHaveCount(1)

  await page.getByRole('link', { name: 'แดชบอร์ด' }).click()
  await expect(page.getByTestId('dash-next-time')).toContainText('19:00')
  await expect(page.getByTestId('dash-next-time')).toContainText('พรุ่งนี้')
  await expect(page.getByText('คลิป 1 → POCO หน้าร้าน (@shop1)')).toBeVisible()
  await expect(page.getByTestId('dash-quota')).toHaveText(/^1\s*\/\s*\d+ คลิป$/)
  await expect(page.getByTestId('dash-phones')).toContainText('/ 1 พร้อมใช้งาน')
  await expect(page.getByTestId('dash-job')).toHaveCount(1)
  await expect(page.getByTestId('dash-job')).toContainText('คลิปพร้อมแล้ว')
  await expect(page.getByText('ไม่มีโพสต์ที่รอคุณ')).toBeVisible()
  await expect(page.getByTestId('me-username')).toHaveText(owner.username)
  await page.screenshot({ path: '../../var/evidence/e2e/dashboard-bento.png', fullPage: true })
})
