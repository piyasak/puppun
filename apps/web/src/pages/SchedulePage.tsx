import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'

/* P4.6: every post across all series, planned time next to what actually happened (G4-05). */

type CalItem = {
  id: string; seq: number; clip_index: number; state: string; reason: string | null
  scheduled_at: string; claimed_at: string | null; started_at: string | null; submitted_at: string | null
  verified_at: string | null; delay_s: number | null; queued_behind: boolean
  job: { id: string; source: string }; device_name: string | null; account: string | null; series_state: string
}

const TZ = 'Asia/Bangkok'
const DAY_MS = 24 * 60 * 60 * 1000
const STATE: Record<string, { text: string; badge: string }> = {
  SCHEDULED: { text: 'รอเวลาโพสต์', badge: 'active' },
  NEEDS_ACTION: { text: 'ต้องดำเนินการ', badge: 'warn' },
  CANCELLED: { text: 'ยกเลิก', badge: 'expired' },
  SKIPPED: { text: 'ข้าม', badge: 'expired' },
  CLAIMED: { text: 'Agent รับงานแล้ว', badge: 'stale' },
  TRANSFERRING: { text: 'กำลังส่งไฟล์', badge: 'stale' },
  PREPARING: { text: 'กำลังเตรียม', badge: 'stale' },
  SUBMITTING: { text: 'กำลังโพสต์', badge: 'stale' },
  VERIFYING: { text: 'กำลังตรวจผล', badge: 'stale' },
  VERIFIED_SUCCESS: { text: 'โพสต์สำเร็จ', badge: 'online' },
  UNKNOWN: { text: 'ไม่ทราบผล', badge: 'revoked' },
  DRY_RUN_DONE: { text: 'ทดสอบเสร็จ (ไม่ได้โพสต์จริง)', badge: 'expired' },
}

function ymd(d: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(d)
}

function weekStart(offsetWeeks: number): Date {
  // Monday 00:00 Bangkok time (UTC+7, no DST).
  const today = new Date(`${ymd(new Date())}T00:00:00+07:00`)
  const dow = new Date(today.getTime() + 7 * 3600 * 1000).getUTCDay()  // weekday in Bangkok, 0 = Sunday
  const monday = today.getTime() - ((dow + 6) % 7) * DAY_MS
  return new Date(monday + offsetWeeks * 7 * DAY_MS)
}

const timeFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, hour: '2-digit', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' })
const fullFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, dateStyle: 'medium', timeStyle: 'short' })

function actual(it: CalItem): string {
  if (!it.claimed_at) return '—'
  const late = it.delay_s ?? 0
  const lateText = late >= 60 ? ` (ช้า ${Math.round(late / 60)} นาที)` : ' (ตรงเวลา)'
  return `รับงาน ${timeFmt.format(new Date(it.claimed_at))}${lateText}${it.verified_at ? ` • ยืนยัน ${timeFmt.format(new Date(it.verified_at))}` : ''}`
}

function Chip({ it }: { it: CalItem }) {
  const s = STATE[it.state] ?? { text: it.state, badge: 'stale' }
  return (
    <Link to={`/jobs/${it.job.id}`} className={`cal-chip cal-${s.badge}`} data-testid="cal-item"
      title={`${fullFmt.format(new Date(it.scheduled_at))} • ${it.device_name} (@${it.account}) • ${s.text}`}>
      <strong>{timeFmt.format(new Date(it.scheduled_at))}</strong> คลิป {it.clip_index}
      <span className="cal-sub">{it.device_name} • {s.text}</span>
      {it.queued_behind && <span className="cal-sub">เข้าคิวต่อจากโพสต์ก่อนหน้าบนเครื่องนี้</span>}
    </Link>
  )
}


export function SchedulePage() {
  const [week, setWeek] = useState(0)
  const [view, setView] = useState<'week' | 'list'>('week')
  const [items, setItems] = useState<CalItem[] | null>(null)
  const [error, setError] = useState('')
  const start = useMemo(() => weekStart(week), [week])
  const end = useMemo(() => new Date(start.getTime() + 7 * DAY_MS), [start])
  const [todayKey] = useState(() => ymd(new Date()))

  const load = useCallback(async () => {
    try {
      const q = `start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`
      setItems((await api<{ items: CalItem[] }>(`/v1/schedule-items?${q}`)).items)
      setError('')
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [start, end])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(timer)
  }, [load])

  const days = Array.from({ length: 7 }, (_, i) => new Date(start.getTime() + i * DAY_MS))
  const byDay = (d: Date) => (items ?? []).filter((it) => ymd(new Date(it.scheduled_at)) === ymd(d))
  const attention = (items ?? []).filter((it) => it.state === 'NEEDS_ACTION' || it.state === 'UNKNOWN').length

  return (
    <Shell title="ตารางโพสต์">
      {error && <Alert kind="error">{error}</Alert>}
      {attention > 0 && <Alert kind="info">มี {attention} โพสต์ในสัปดาห์นี้ที่ต้องดำเนินการหรือไม่ทราบผล</Alert>}
      <section className="card">
        <div className="cal-toolbar">
          <div className="row-actions">
            <button type="button" className="btn btn-secondary btn-small" onClick={() => setWeek(week - 1)}>← สัปดาห์ก่อน</button>
            <button type="button" className="btn btn-secondary btn-small" onClick={() => setWeek(0)} disabled={week === 0}>สัปดาห์นี้</button>
            <button type="button" className="btn btn-secondary btn-small" onClick={() => setWeek(week + 1)}>สัปดาห์ถัดไป →</button>
          </div>
          <strong data-testid="cal-range">{dayFmt.format(days[0])} – {dayFmt.format(days[6])}</strong>
          <div className="tabs" role="tablist" aria-label="มุมมอง">
            <button type="button" role="tab" aria-selected={view === 'week'} className={`tab${view === 'week' ? ' active' : ''}`} onClick={() => setView('week')}>รายสัปดาห์</button>
            <button type="button" role="tab" aria-selected={view === 'list'} className={`tab${view === 'list' ? ' active' : ''}`} onClick={() => setView('list')}>รายการ</button>
          </div>
        </div>
        <p className="hint">เวลาประเทศไทย • เวลานัดคำนวณจาก Server; "เวลาจริง" คือตอนที่ Agent รับงานและผลที่ยืนยันแล้ว</p>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {items?.length === 0 && <p className="muted">ไม่มีโพสต์ในสัปดาห์นี้ — ตั้งเวลาได้จากหน้า <Link to="/jobs">งานผลิตคลิป</Link></p>}

        {items && items.length > 0 && view === 'week' && (
          <div className="cal-week">
            {days.map((d) => (
              <div key={d.toISOString()} className={`cal-day${ymd(d) === todayKey ? ' cal-today' : ''}`}>
                <div className="cal-day-head">{dayFmt.format(d)}</div>
                {byDay(d).map((it) => <Chip key={it.id} it={it} />)}
              </div>
            ))}
          </div>
        )}

        {items && items.length > 0 && view === 'list' && (
          <table className="table" data-testid="cal-table">
            <thead><tr><th>เวลานัด</th><th>เวลาจริง</th><th>โทรศัพท์</th><th>งาน / คลิป</th><th>สถานะ</th></tr></thead>
            <tbody>
              {items.map((it) => {
                const s = STATE[it.state] ?? { text: it.state, badge: 'stale' }
                return (
                  <tr key={it.id} data-testid="cal-row">
                    <td>{fullFmt.format(new Date(it.scheduled_at))}{it.queued_behind && <div className="hint">เข้าคิวต่อจากโพสต์ก่อนหน้า</div>}</td>
                    <td>{actual(it)}</td>
                    <td>{it.device_name}<div className="hint">@{it.account}</div></td>
                    <td><Link to={`/jobs/${it.job.id}`}>{it.job.source}</Link><div className="hint">คลิป {it.clip_index}</div></td>
                    <td><span className={`badge badge-${s.badge}`}>{s.text}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </Shell>
  )
}
