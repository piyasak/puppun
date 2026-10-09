/*
 * P4.2 + G3-05 browser journey: schedule the approved clips of a job on a phone. The preview is
 * calculated by the server; only approved clips are included; editing a clip's text parks its
 * post until the new text is approved; a series can be cancelled.
 */
import { expect, test } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { FakeAgent, sampleClip } from './agentSim'
import { agentSession, signUpAndOnboard } from './helpers'

function tomorrow(): string {
  const d = new Date(Date.now() + 24 * 60 * 60 * 1000)
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(d)  // YYYY-MM-DD
}

test('schedule approved clips, follow an edit, cancel the series', async ({ page, request }) => {
  test.setTimeout(120_000)
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  const phoneId = await agent.registerPhone(`SCH${randomUUID().slice(0, 8).toUpperCase()}`)
  await page.goto(`/devices?edit=${phoneId}`)
  await page.getByLabel('ชื่อเรียกเครื่อง').fill('POCO หน้าร้าน')
  await page.getByLabel('บัญชี TikTok ที่ต้องโพสต์').fill('@shop1')
  await page.getByRole('button', { name: 'บันทึก' }).click()
  await expect(page.getByTestId('device-row')).toContainText('@shop1')

  // A job with two delivered clips (simulated Agent, real 1080x1920 file)
  await page.getByRole('link', { name: 'สร้างงาน' }).click()
  await page.getByLabel('ไฟล์วิดีโอบนเครื่อง Agent').check()
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ตอนพิเศษ.mp4')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByLabel('ความยาวต่อคลิป').fill('40')  // clips of 32–40 s (the sample clips are 35 s)
  await page.getByLabel('กำหนดเอง').check()
  await page.getByLabel('จำนวนคลิป').fill('2')
  await page.getByRole('button', { name: 'ถัดไป' }).click()
  await page.getByRole('button', { name: 'สร้างงาน' }).click()
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  const jobId = page.url().split('/').pop()!
  expect((await agent.claim()).id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 600, possible_clips: 2 })
  await agent.event(jobId, 'stage', { stage: 'RENDERING' })
  const clip = sampleClip(35)
  await agent.deliver(jobId, 1, clip, 35_000)
  await agent.deliver(jobId, 2, clip, 35_000)
  await agent.event(jobId, 'completed')
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })

  const good = page.getByTestId('clip-card').nth(0)
  await good.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 1)' }).click()
  await expect(good.getByTestId('approval')).toHaveText('อนุมัติแล้ว')

  // Server preview: only the approved clip, at the chosen time
  const panel = page.getByRole('region', { name: 'ตั้งเวลาโพสต์' })
  await expect(panel).toContainText('(1 จาก 2 คลิป)')
  await panel.getByLabel('เริ่ม (เวลาประเทศไทย)').fill(`${tomorrow()}T19:00`)
  await panel.getByLabel('โพสต์ทุก').selectOption({ label: '2 ชั่วโมง' })
  await panel.getByRole('button', { name: 'ดูตัวอย่างเวลา' }).click()
  const rows = panel.getByTestId('preview-row')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('คลิป 1 (ข้อความเวอร์ชัน 1)')
  await expect(rows.first()).toContainText('19:00')
  await expect(panel).toContainText('ไม่รวม: คลิป 2 (ยังไม่อนุมัติ)')
  await panel.getByRole('button', { name: 'ยืนยันตั้งเวลา 1 โพสต์' }).click()
  const item = panel.getByTestId('schedule-item')
  await expect(item).toHaveCount(1)
  await expect(item).toContainText('รอเวลาโพสต์')
  await expect(panel.getByTestId('series')).toContainText('POCO หน้าร้าน (@shop1)')

  // Edit the scheduled clip's caption: its post waits for a new approval (G3-05)
  await good.getByLabel('คำบรรยาย (Caption)').fill('ตอนพิเศษ ห้ามพลาด')
  await good.getByRole('button', { name: 'บันทึกข้อความ' }).click()
  await expect(item).toContainText('ต้องดำเนินการ')
  await expect(item).toContainText('อนุมัติข้อความล่าสุดของคลิปนี้เพื่อให้โพสต์ต่อ')
  await good.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 2)' }).click()
  await expect(item).toContainText('รอเวลาโพสต์')
  await expect(item).toContainText('คลิป 1 (v2)')

  // Pause, then resume through the server's preview (nothing was missed: times stay)
  const series = panel.getByTestId('series')
  await series.getByRole('button', { name: 'หยุดชั่วคราว' }).click()
  await expect(series).toContainText('หยุดชั่วคราว')
  await series.getByRole('button', { name: 'ทำงานต่อ…' }).click()
  await expect(page.getByRole('dialog')).toContainText('ใช้เวลาเดิม')
  await page.getByRole('dialog').getByRole('button', { name: 'ทำงานต่อ' }).click()
  await expect(series).toContainText('กำลังใช้งาน')

  // Move the unstarted post: outside the window is refused, inside is saved
  await item.getByRole('button', { name: 'แก้เวลา' }).click()
  await item.getByLabel('เวลาใหม่ของโพสต์ 1').fill(`${tomorrow()}T22:00`)
  await item.getByRole('button', { name: 'บันทึก' }).click()
  await expect(panel.getByRole('alert')).toHaveText('เวลาอยู่นอกช่วงที่โพสต์ได้')
  await item.getByRole('button', { name: 'แก้เวลา' }).click()
  await item.getByLabel('เวลาใหม่ของโพสต์ 1').fill(`${tomorrow()}T20:30`)
  await item.getByRole('button', { name: 'บันทึก' }).click()
  await expect(item).toContainText('20:30')
  await expect(panel.getByRole('alert')).toHaveCount(0)  // the earlier refusal is gone
  await page.screenshot({ path: '../../var/evidence/e2e/schedule.png', fullPage: true })

  // The week calendar shows the post with its planned time (tomorrow may fall in next week)
  const jobUrl = page.url()
  await page.getByRole('link', { name: 'ตารางโพสต์' }).click()
  const tomorrowIsMonday = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Bangkok', weekday: 'short' })
    .format(new Date(Date.now() + 24 * 60 * 60 * 1000)) === 'Mon'
  if (tomorrowIsMonday) await page.getByRole('button', { name: 'สัปดาห์ถัดไป →' }).click()
  const chip = page.getByTestId('cal-item')
  await expect(chip).toHaveCount(1)
  await expect(chip).toContainText('20:30')
  await expect(chip).toContainText('POCO หน้าร้าน')
  await page.getByRole('tab', { name: 'รายการ' }).click()
  await expect(page.getByTestId('cal-row')).toContainText('@shop1')
  await expect(page.getByTestId('cal-row')).toContainText('รอเวลาโพสต์')
  await page.screenshot({ path: '../../var/evidence/e2e/calendar.png', fullPage: true })
  await page.goto(jobUrl)

  await panel.getByRole('button', { name: 'ยกเลิกทั้งตาราง' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'ยกเลิกทั้งตาราง' }).click()
  await expect(item).toContainText('ยกเลิกแล้ว')
  await expect(panel.getByTestId('series')).toContainText('ยกเลิกแล้ว')
})
