/*
 * NF-09 / G7-04: every page is usable at 360 px and at 200 % zoom (no sideways scrolling), passes
 * axe WCAG 2.1 A/AA rules, has lang="th", and can be driven with the keyboard with a visible focus.
 * Pages are checked with real data (a phone and a job with a delivered clip), not only empty states.
 * Screenshots: var/evidence/e2e/quality/ (not committed).
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { FakeAgent, sampleClip } from './agentSim'
import { agentSession, signUpAndOnboard } from './helpers'

const VIEWS = [
  { name: 'mobile-360', width: 360, height: 780 },
  { name: 'zoom-200', width: 640, height: 400 },  // a 1280x800 window at 200 % zoom
  { name: 'desktop', width: 1280, height: 800 },
]
const PUBLIC = ['/', '/login', '/signup', '/forgot', '/auth/confirm']  // '/' = landing page for visitors

/** Elements that stick out past the right edge without being inside their own scroll area. */
async function overflow(page: Page) {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth
    if (document.documentElement.scrollWidth <= width + 1) return []
    const scrolls = (el: Element | null): boolean => {
      for (let e = el?.parentElement; e; e = e.parentElement) {
        const s = getComputedStyle(e)
        if (/(auto|scroll)/.test(s.overflowX) && e.scrollWidth > e.clientWidth) return true
      }
      return false
    }
    return [...document.querySelectorAll('body *')]
      .filter((e) => e.getBoundingClientRect().right > width + 1 && !scrolls(e))
      .slice(0, 5)
      .map((e) => `${e.tagName.toLowerCase()}.${(e.getAttribute('class') ?? '').split(' ')[0]} "${(e.textContent ?? '').trim().slice(0, 40)}"`)
  })
}

async function check(page: Page, path: string, problems: string[], prepare?: (p: Page) => Promise<void>, label = path) {
  for (const view of VIEWS) {
    await page.setViewportSize({ width: view.width, height: view.height })
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await page.evaluate(async () => {  // let scroll-reveal sections appear before checking
      for (let y = 0; y < document.body.scrollHeight; y += 400) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 30)) }
      scrollTo(0, 0)
    })
    if (prepare) await prepare(page)
    const out = await overflow(page)
    if (out.length) problems.push(`${label} @${view.name}: sideways scroll — ${out.join('; ')}`)
    await page.screenshot({ path: `../../var/evidence/e2e/quality/${label.replace(/[/:? ]/g, '_')}-${view.name}.png`, fullPage: true })
  }
  // Both themes: dark (default) and light (ThemeToggle). Colours have 200 ms transitions, and a fast
  // machine (CI) ran axe mid-fade after the switch and measured in-between colours; reduced motion
  // turns every transition off, and two frames let the new theme paint before measuring.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const theme of ['dark', 'light']) {
    await page.evaluate(async (t) => {
      if (t === 'light') document.documentElement.dataset.theme = 'light'; else delete document.documentElement.dataset.theme
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
    }, theme)
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    for (const v of axe.violations) {
      problems.push(`${label} [${theme}]: axe ${v.id} (${v.impact}) — ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(', ')}`)
    }
  }
  await page.evaluate(() => { delete document.documentElement.dataset.theme })
  await page.emulateMedia({ reducedMotion: null })
  expect(await page.getAttribute('html', 'lang')).toBe('th')
}

test('pages work at 360 px, at 200 % zoom and pass axe', async ({ page, browser, request }) => {
  test.setTimeout(240_000)
  const problems: string[] = []

  const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:5173', locale: 'th-TH' })
  const anon = await ctx.newPage()
  for (const path of PUBLIC) await check(anon, path, problems, undefined, path === '/' ? '/landing' : path)
  await ctx.close()

  // Real data: a named phone and a job with one delivered clip
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  const phoneId = await agent.registerPhone(`QA${randomUUID().slice(0, 8).toUpperCase()}`)
  await page.goto(`/devices?edit=${phoneId}`)
  // Long but valid values (name ≤ 60, handle ≤ 25), so wrapping is part of what is checked
  await page.getByLabel('ชื่อเรียกเครื่อง').fill('POCO หน้าร้านสาขาลาดพร้าว ชั้น 2 โซนไลฟ์สดตอนเย็น')
  await page.getByLabel('บัญชี TikTok ที่ต้องโพสต์').fill('@punpun.shop_ladprao_9')
  await page.getByRole('button', { name: 'บันทึก' }).click()
  await expect(page.getByTestId('device-row')).toContainText('@punpun.shop_ladprao_9')
  await page.getByRole('link', { name: 'สร้างงาน' }).click()
  await page.getByLabel(/วิดีโอเต็มบนเครื่อง Agent/).check()
  await page.getByLabel('ชื่อไฟล์วิดีโอ').fill('ตอนพิเศษ-ชื่อไฟล์ยาวมากเพื่อทดสอบการตัดบรรทัด.mp4')
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
  // ...approved and scheduled, so the calendar and the schedule list have rows
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })
  await page.getByRole('button', { name: 'อนุมัติคลิปนี้ (ข้อความเวอร์ชัน 1)' }).click()
  const panel = page.getByRole('region', { name: 'ตั้งเวลาโพสต์' })
  const tomorrow = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(new Date(Date.now() + 864e5))
  await panel.getByLabel('เริ่ม (เวลาประเทศไทย)').fill(`${tomorrow}T19:00`)
  await panel.getByRole('button', { name: 'ดูตัวอย่างเวลา' }).click()
  await panel.getByRole('button', { name: 'ยืนยันตั้งเวลา 1 โพสต์' }).click()
  await expect(panel.getByTestId('schedule-item')).toHaveCount(1)

  for (const path of ['/', '/environments', '/agent-tokens', '/agents', '/devices', '/create', '/jobs',
    `/jobs/${jobId}`, '/schedule', '/billing']) {
    await check(page, path, problems)
  }
  await check(page, '/schedule', problems, (p) => p.getByRole('tab', { name: 'รายการ' }).click(), '/schedule list')
  expect(problems, problems.join('\n')).toEqual([])
})

test('the sign-in form works from the keyboard with a visible focus and clear errors', async ({ page }) => {
  await page.goto('/login')
  const focusVisible = () => page.evaluate(() => {
    const s = getComputedStyle(document.activeElement as Element)
    return s.outlineStyle !== 'none' && s.outlineWidth !== '0px' || s.boxShadow !== 'none'
  })
  const seen: string[] = []
  for (let i = 0; i < 8 && !seen.includes('BUTTON:เข้าสู่ระบบ'); i++) {
    await page.keyboard.press('Tab')
    seen.push(await page.evaluate(() => {
      const e = document.activeElement as HTMLElement
      return `${e.tagName}:${e.getAttribute('aria-label') ?? e.textContent?.trim() ?? ''}`
    }))
    expect(await focusVisible(), `focus not visible on ${seen.at(-1)}`).toBe(true)
  }
  expect(seen).toContain('BUTTON:เข้าสู่ระบบ')
  await page.keyboard.press('Enter')  // submit empty from the keyboard
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByLabel('อีเมล').focus()
  await page.keyboard.type('nobody@example.com')
  await page.getByLabel('รหัสผ่าน', { exact: true }).focus()
  await page.keyboard.type('wrong-password-123')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('alert')).toHaveText('อีเมลหรือรหัสผ่านไม่ถูกต้อง')
})

/** Presses Tab until the focused element's accessible text matches `name`; every stop must show focus. */
async function tabTo(page: Page, name: RegExp, max = 60) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const here = await page.evaluate(() => {
      const e = document.activeElement as HTMLElement
      const label = e.id ? document.querySelector(`label[for="${e.id}"]`)?.textContent : null
      const s = getComputedStyle(e)
      return { text: `${e.getAttribute('aria-label') ?? ''} ${label ?? ''} ${e.closest('label')?.textContent ?? ''} ${e.tagName === 'BUTTON' || e.tagName === 'A' ? e.textContent : ''}`.trim(),
        visible: (s.outlineStyle !== 'none' && s.outlineWidth !== '0px') || s.boxShadow !== 'none' }
    })
    expect(here.visible, `focus not visible on "${here.text}"`).toBe(true)
    if (name.test(here.text)) return
  }
  throw new Error(`Tab never reached ${name}`)
}

test('create, approve and schedule a job with the keyboard only', async ({ page, request }) => {
  test.setTimeout(120_000)
  const owner = await signUpAndOnboard(page, request)
  const agent = new FakeAgent(request, await agentSession(page, request, owner.username))
  const phoneId = await agent.registerPhone(`KB${randomUUID().slice(0, 8).toUpperCase()}`)
  await page.goto(`/devices?edit=${phoneId}`)
  await page.getByLabel('บัญชี TikTok ที่ต้องโพสต์').fill('@kb_shop')
  await page.getByRole('button', { name: 'บันทึก' }).click()
  await expect(page.getByTestId('device-row')).toContainText('@kb_shop')

  // Create job wizard
  await page.goto('/create')
  await tabTo(page, /ลิงก์ YouTube/)
  await page.keyboard.press('ArrowDown')  // radio group: next option
  await expect(page.getByLabel(/วิดีโอเต็มบนเครื่อง Agent/)).toBeChecked()
  await tabTo(page, /ชื่อไฟล์วิดีโอ/)
  await page.keyboard.type('คีย์บอร์ด.mp4')
  await tabTo(page, /^ถัดไป$/)
  await page.keyboard.press('Enter')
  await tabTo(page, /ความยาวต่อคลิป/)
  await page.keyboard.press('Control+A')
  await page.keyboard.type('40')
  await tabTo(page, /คำนวณจากความยาวต้นฉบับ/)
  await page.keyboard.press('ArrowDown')  // radio group: "set it myself"
  await expect(page.getByLabel('กำหนดเอง')).toBeChecked()
  await tabTo(page, /จำนวนคลิป/)
  await page.keyboard.press('Control+A')
  await page.keyboard.type('1')
  await tabTo(page, /^ถัดไป$/)
  await page.keyboard.press('Enter')
  await tabTo(page, /^สร้างงาน$/)
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/)
  const jobId = page.url().split('/').pop()!
  expect((await agent.claim()).id).toBe(jobId)
  await agent.event(jobId, 'source_validated', { duration_s: 600, possible_clips: 1 })
  await agent.event(jobId, 'stage', { stage: 'RENDERING' })
  await agent.deliver(jobId, 1, sampleClip(35), 35_000)
  await agent.event(jobId, 'completed')
  await expect(page.getByTestId('job-state')).toHaveText('คลิปพร้อมแล้ว', { timeout: 15_000 })

  // Approve, preview, schedule
  await page.locator('body').focus()
  await tabTo(page, /อนุมัติคลิปนี้/)
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('approval')).toHaveText('อนุมัติแล้ว')
  await tabTo(page, /ดูตัวอย่างเวลา/)
  await page.keyboard.press('Enter')
  await tabTo(page, /ยืนยันตั้งเวลา 1 โพสต์/)
  await page.keyboard.press('Enter')
  const panel = page.getByRole('region', { name: 'ตั้งเวลาโพสต์' })
  await expect(panel.getByTestId('schedule-item')).toHaveCount(1)

  // Confirm dialog: focus moves in, Esc closes and gives focus back, Enter confirms
  await tabTo(page, /ยกเลิกทั้งตาราง/)
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'ยกเลิกทั้งตาราง' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await tabTo(page, /ยกเลิกทั้งตาราง|ยืนยัน/, 4)
  await page.keyboard.press('Enter')
  await expect(panel.getByTestId('series')).toContainText('ยกเลิกแล้ว')
})

test('phone menu opens, closes with Esc and on navigation, and the theme choice is remembered', async ({ page, request }) => {
  await signUpAndOnboard(page, request)
  await page.setViewportSize({ width: 360, height: 780 })
  await page.goto('/jobs')
  const menu = page.getByRole('button', { name: 'เมนู' })
  await expect(page.getByRole('navigation', { name: 'เมนูหลัก' })).toBeHidden()
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('navigation', { name: 'เมนูหลัก' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('navigation', { name: 'เมนูหลัก' })).toBeHidden()
  await expect(menu).toBeFocused()
  await page.keyboard.press('Enter')
  await page.getByRole('link', { name: 'ตารางโพสต์' }).click()
  await expect(page).toHaveURL(/\/schedule$/)
  await expect(page.getByRole('navigation', { name: 'เมนูหลัก' })).toBeHidden()

  // Theme: dark by default, light is remembered across reloads
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBeUndefined()
  await menu.click()
  await page.getByRole('button', { name: 'ธีมสว่าง' }).click()
  await expect(page.getByRole('button', { name: 'ธีมสว่าง' })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('light')
})
