/*
 * P3.4 browser journey (FR-02, FR-06..08, G3-03/G3-05 UI): the owner creates a job in the wizard,
 * a simulated Agent (API calls) delivers one real 1080x1920 clip and one broken file, the web
 * shows progress, server checks and a playable preview, then caption edits and approvals,
 * including "edit after approval needs a new approval".
 */
import { expect, test } from '@playwright/test'
import { FakeAgent, sampleClip, sampleStill } from './agentSim'
import { agentSession, signUpAndOnboard } from './helpers'

test('create a job, watch it progress, preview, edit and approve clips', async ({ page, request }) => {
  test.setTimeout(120_000)
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))

  // Wizard: source -> format -> review
  await page.getByRole('link', { name: 'สร้างงาน' }).click()
  await page.getByLabel('ไฟล์วิดีโอบนเครื่อง Agent').check()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByRole('alert')).toHaveText('ใส่ชื่อไฟล์วิดีโอ')
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('C:\\Videos\\ตอนพิเศษ.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByRole('alert')).toHaveText('ใส่เฉพาะชื่อไฟล์ ไม่ต้องใส่โฟลเดอร์')
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ตอนพิเศษ.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByLabel('ความยาวต่อคลิป').fill('40')  // clips of 32–40 s (the sample clips are 35 s)
  await page.getByLabel('กำหนดเอง').check()
  await page.getByLabel('จำนวนคลิป').fill('2')
  await page.getByLabel(/อนุมัติอัตโนมัติ/).check()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByRole('alert')).toHaveText('ยืนยันการอนุมัติอัตโนมัติก่อน')
  await page.getByLabel(/ตรวจเองทุกคลิป/).check()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByTestId('quota-preview')).toHaveText('ใช้สูงสุด 2 คลิป จากที่เหลือ 30 คลิปเดือนนี้ — หักเฉพาะคลิปที่ส่งถึงจริง')
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  await expect(page.getByTestId('job-state')).toHaveText('รอ Agent รับงาน')
  await expect(page.locator('#job-title')).toHaveText('ไฟล์บนเครื่อง: ตอนพิเศษ.mp4')
  const jobId = page.url().split('/').pop()!

  // The Agent picks it up; the page follows without a reload.
  const claimed = await agent.claim()
  expect(claimed.id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 600, possible_clips: 2 })
  await agent.event(jobId, 'stage', { stage: 'RENDERING' })
  await expect(page.getByTestId('job-state')).toHaveText('กำลังสร้างคลิป', { timeout: 15_000 })
  await expect(page.getByTestId('job-quota')).toHaveText('จอง 2 • ใช้ 0 • คืน 0', { timeout: 15_000 })

  await agent.deliver(jobId, 1, sampleClip(35), 35_000)
  await agent.deliver(jobId, 2, Buffer.from('this is not a video file'), 35_000)
  await agent.event(jobId, 'completed')
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })
  await expect(page.getByTestId('job-quota')).toHaveText('จอง 2 • ใช้ 2 • คืน 0')

  const [good, broken] = [page.getByTestId('clip-card').nth(0), page.getByTestId('clip-card').nth(1)]
  await expect(good).toContainText('ผ่านการตรวจไฟล์')
  await expect(good).toContainText('ช่วงต้นฉบับ 1:00–1:35')
  await expect(broken).toContainText('ไม่ผ่านการตรวจไฟล์')
  await expect(broken.getByRole('button', { name: /อนุมัติคลิปนี้/ })).toBeDisabled()

  // Preview through the short-lived signed link. Edge (Windows) plays H.264; open-source Chromium
  // in CI has no H.264 decoder, so there only the signed link itself is checked.
  await good.getByRole('button', { name: /ดูตัวอย่าง/ }).click()
  if (process.platform === 'win32') {
    const video = good.getByTestId('clip-video')
    await expect(video).toBeVisible()
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1)
    expect(await video.evaluate((v: HTMLVideoElement) => Math.round(v.duration))).toBe(35)
  }

  // Edit -> approve -> edit again voids the approval -> approve the new version
  await good.getByLabel('คำบรรยาย (Caption)').fill('ตอนพิเศษ ห้ามพลาด')
  await good.getByLabel('แฮชแท็ก').fill('#คลิปสั้น #ห้ามพลาด')
  await good.getByRole('button', { name: 'บันทึกข้อความ' }).click()
  await expect(good).toContainText('ข้อความเวอร์ชัน 2')
  await good.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 2)' }).click()
  await expect(good.getByTestId('approval')).toHaveText('อนุมัติแล้ว')
  await good.getByLabel('คำบรรยาย (Caption)').fill('ตอนพิเศษ ดูให้จบ')
  await good.getByRole('button', { name: 'บันทึกข้อความ' }).click()
  await expect(good.getByTestId('approval')).toHaveText('ยังไม่อนุมัติ')
  await expect(good).toContainText('ข้อความถูกแก้หลังอนุมัติ ต้องตรวจและอนุมัติใหม่')
  await good.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 3)' }).click()
  await expect(good.getByTestId('approval')).toHaveText('อนุมัติแล้ว')
  await page.screenshot({ path: '../../var/evidence/e2e/job-detail.png', fullPage: true })

  // List: the job sits under "รอตรวจ"
  await page.getByRole('link', { name: 'กลับไปรายการงาน' }).click()
  await page.getByRole('tab', { name: /รอตรวจ/ }).click()
  await expect(page.getByTestId('job-row')).toHaveCount(1)
  await expect(page.getByTestId('job-row')).toContainText('ไฟล์บนเครื่อง: ตอนพิเศษ.mp4')
  await page.getByRole('tab', { name: /กำลังผลิต/ }).click()
  await expect(page.getByTestId('job-row')).toHaveCount(0)
})

test('cancel a job before the Agent starts', async ({ page, request }) => {
  await signUpAndOnboard(page, request)
  await page.getByRole('link', { name: 'Environments' }).click()
  await page.getByLabel('ชื่อ Environment').fill('บ้าน')
  await page.getByRole('button', { name: 'สร้าง Environment' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: 'บ้าน' })).toBeVisible()
  await page.getByRole('link', { name: 'สร้างงาน' }).click()
  await page.getByLabel('ลิงก์ต้นฉบับ').fill('http://example.com/video')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByRole('alert')).toContainText('https://')
  await page.getByLabel('ลิงก์ต้นฉบับ').fill('https://example.com/video')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page.getByRole('alert')).toHaveText('ลิงก์นี้ใช้ไม่ได้ รองรับเฉพาะลิงก์ https ของ YouTube และ Bilibili')
  await page.getByRole('button', { name: 'ย้อนกลับ' }).click()
  await page.getByRole('button', { name: 'ย้อนกลับ' }).click()
  await page.getByLabel('ลิงก์ต้นฉบับ').fill('https://www.youtube.com/watch?v=PBES5k67dhI')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page.getByTestId('job-state')).toHaveText('รอ Agent รับงาน')
  await expect(page.locator('#job-title')).toHaveText('https://www.youtube.com/watch?v=PBES5k67dhI')  // a link job is titled by its link

  await page.getByRole('button', { name: 'ยกเลิกงาน' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิกงาน' }).click()
  await expect(page.getByTestId('job-state')).toHaveText('ยกเลิกแล้ว')
  await expect(page.getByTestId('job-quota')).toHaveText('จอง 0 • ใช้ 0 • คืน 0')
  await expect(page.getByRole('button', { name: 'ยกเลิกงาน' })).toHaveCount(0)
})

test('by default the clip count follows the source, with clips of about 300 s', async ({ page, request }) => {
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  await page.goto('/create')
  await page.getByLabel('ไฟล์วิดีโอบนเครื่อง Agent').check()
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ไลฟ์ยาว.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByLabel('ความยาวต่อคลิป')).toHaveValue('300')
  await expect(page.getByLabel('คำนวณจากความยาวต้นฉบับ')).toBeChecked()
  await expect(page.getByText('ตัดตรงช่วงเงียบ ยาวประมาณ 240–300 วินาที (5.0 นาที)')).toBeVisible()
  await expect(page.getByLabel('จำนวนคลิป')).toHaveCount(0)  // no count to type
  await expect(page.getByLabel(/ลบไฟล์คลิปออกจากเครื่อง Agent ถาวรหลังโพสต์สำเร็จ/)).not.toBeChecked()  // kept unless asked
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByTestId('after-post-preview')).toHaveText('เก็บไฟล์คลิปไว้')
  await expect(page.getByTestId('clips-preview')).toHaveText('คำนวณจากความยาวต้นฉบับ คลิปละประมาณ 240–300 วินาที')
  await expect(page.getByTestId('quota-preview')).toContainText('ใช้ตามจำนวนที่ต้นฉบับตัดได้')
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  await expect(page.getByText('คำนวณจากต้นฉบับ • รอ Agent วัดความยาว')).toBeVisible()

  // The Agent measures a 42-minute source: 9 clips; the page follows
  const jobId = page.url().split('/').pop()!
  expect((await agent.claim()).id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 2530, possible_clips: 9 })
  await expect(page.getByText('คำนวณจากต้นฉบับ • ได้ 9 คลิป')).toBeVisible({ timeout: 15_000 })
})

test('a clip kept on the Agent shows its frames and where the file is, and can be approved', async ({ page, request }) => {
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  await page.goto('/create')
  await page.getByLabel('ไฟล์วิดีโอบนเครื่อง Agent').check()
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ไลฟ์.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByLabel('ความยาวต่อคลิป').fill('40')
  await page.getByLabel(/ลบไฟล์คลิปออกจากเครื่อง Agent ถาวรหลังโพสต์สำเร็จ/).check()  // chosen when creating the job
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await expect(page.getByTestId('after-post-preview')).toHaveText('ลบไฟล์คลิปบนเครื่อง Agent ถาวร')
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  await expect(page.getByTestId('job-after-post')).toHaveText('ลบไฟล์คลิปบนเครื่อง Agent ถาวรเมื่อโพสต์สำเร็จ')
  const jobId = page.url().split('/').pop()!
  expect((await agent.claim()).id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 80, possible_clips: 2 })
  await agent.event(jobId, 'stage', { stage: 'RENDERING' })
  const still = sampleStill()
  await agent.deliverKept(jobId, 1, 40_000, still)
  await agent.deliverKept(jobId, 2, 40_000, still)
  await agent.event(jobId, 'completed')
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })

  const first = page.getByTestId('clip-card').nth(0)
  const img = first.getByRole('img', { name: 'ภาพจาก 3 ช่วงของคลิป 1' })
  await expect(img).toBeVisible()
  expect(await img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBe(810)  // the real still loaded
  await expect(first.getByTestId('agent-path')).toHaveText(['D:', 'punpun', 'clips', jobId, 'clip_01.mp4'].join('\\'))
  await expect(first.getByText('วิดีโอเก็บไว้บนเครื่อง Agent (ไม่ได้อัปโหลด)')).toBeVisible()
  await expect(first.getByTestId('clip-video')).toHaveCount(0)  // nothing to play: the video never left the PC
  await first.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 1)' }).click()
  await expect(first.getByTestId('approval')).toHaveText('อนุมัติแล้ว')
  await page.screenshot({ path: '../../var/evidence/e2e/clip-kept-on-agent.png', fullPage: true })

  // PO 2026-10-10: "โพสต์ทันที" on an approved clip asks for a ready phone first
  await first.getByRole('button', { name: 'โพสต์ทันที' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('ยังไม่มีโทรศัพท์ที่พร้อม', { exact: false })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'โพสต์ทันที' })).toBeDisabled()
  await dialog.getByRole('button', { name: 'ยกเลิก' }).click()

  // PO 2026-10-10: the clips folder moved on the PC -> start the job again from its page
  await page.getByRole('button', { name: 'เริ่มงานใหม่' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'เริ่มงานใหม่' }).click()
  await expect(page.getByText('Agent จะหาไฟล์คลิปที่ถูกย้ายหรือทำไฟล์ใหม่', { exact: false })).toBeVisible()
  const again = await agent.claim() as unknown as { id: string; remake: number[] }
  expect(again.id).toBe(jobId)
  expect(again.remake).toEqual([1, 2])  // both kept clips: found where they were moved, or made again
  await expect(first.getByTestId('approval')).toHaveText('อนุมัติแล้ว')  // nothing is lost by asking
})
