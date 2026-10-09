/*
 * Dashboard (E-47 step 3): what needs attention today, as a bento of cards. Everything comes from the
 * existing APIs; times are computed by the server and only formatted here (Asia/Bangkok).
 * Each card loads on its own, so one failing call never blanks the page.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api, type Me } from '../lib/api'
import { STATE as JOB_STATE, sourceLabel, type Job } from '../lib/jobs'
import { POST_STATE, TZ, UPCOMING } from '../lib/posts'

type Post = {
  id: string; clip_index: number; state: string; scheduled_at: string
  job: { id: string; source: string }; device_name: string | null; account: string | null
}
type Subscription = {
  status: string; plan: { name: string; code: string }
  quota: { limit: number; used: number; available: number; cycle_end: string }
}
type Device = { id: string; readiness: string; unbound_at: string | null; missing_details: string[] }
type Loaded<T> = { data?: T; error?: string }

const REFRESH_MS = 30_000
const timeFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, hour: '2-digit', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short' })
const dateFmt = new Intl.DateTimeFormat('th-TH', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' })

/** Loads one card's data now and every REFRESH_MS. `path` is read once (a function for time-based ranges). */
function useLoad<T>(path: string | (() => string)): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({})
  const pathRef = useRef(path)
  useEffect(() => {
    let alive = true
    const p = pathRef.current
    const load = () => api<T>(typeof p === 'function' ? p() : p)
      .then((data) => alive && setState({ data }))
      .catch((e: ApiError) => alive && setState((s) => ({ ...s, error: e.message })))
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  return state
}

function untilText(iso: string, now: number): string {
  const min = Math.round((new Date(iso).getTime() - now) / 60_000)
  if (min <= 0) return 'ถึงเวลาแล้ว'
  if (min < 60) return `อีก ${min} นาที`
  const h = Math.floor(min / 60)
  if (h < 24) return `อีก ${h} ชม. ${min % 60} นาที`
  return `อีก ${Math.floor(h / 24)} วัน`
}

function dayLabel(iso: string, now: number): string {
  const ymd = (t: number) => new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(t)
  const t = new Date(iso).getTime()
  if (ymd(t) === ymd(now)) return 'วันนี้'
  if (ymd(t) === ymd(now + 86_400_000)) return 'พรุ่งนี้'
  return dayFmt.format(t)
}

function NextPost() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(t) }, [])
  const posts = useLoad<{ items: Post[] }>(() => {
    const start = new Date(Date.now() - 3_600_000).toISOString()
    const end = new Date(Date.now() + 14 * 86_400_000).toISOString()
    return `/v1/schedule-items?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
  })
  const upcoming = (posts.data?.items ?? []).filter((p) => UPCOMING.includes(p.state))
  const next = upcoming[0]

  return (
    <section className="card dash-card dash-next" aria-labelledby="dash-next-title">
      <h2 id="dash-next-title" className="dash-label">โพสต์ถัดไป · เวลาประเทศไทย</h2>
      {posts.error && <Alert kind="error">{posts.error}</Alert>}
      {!posts.data && !posts.error && <p className="muted" role="status">กำลังโหลด…</p>}
      {posts.data && !next && (
        <div className="dash-empty">
          <p>ยังไม่มีโพสต์ที่ตั้งเวลาไว้ใน 14 วันข้างหน้า</p>
          <p className="muted">อนุมัติคลิปในหน้างานผลิตคลิป แล้วตั้งเวลาโพสต์จากหน้านั้น</p>
          <Link to="/jobs" className="btn btn-secondary btn-small">ไปที่งานผลิตคลิป</Link>
        </div>
      )}
      {next && (
        <>
          <p className="dash-big" data-testid="dash-next-time">
            {timeFmt.format(new Date(next.scheduled_at))}
            <span className="dash-big-sub">
              {dayLabel(next.scheduled_at, now)}
              {new Date(next.scheduled_at).getTime() - now < 86_400_000 && ` · ${untilText(next.scheduled_at, now)}`}
            </span>
          </p>
          <p className="dash-sub">
            คลิป {next.clip_index} → {next.device_name ?? 'โทรศัพท์'}{next.account ? ` (@${next.account.replace(/^@/, '')})` : ''}
            {next.state !== 'SCHEDULED' && <> · <span className={`badge badge-${POST_STATE[next.state]?.badge ?? 'stale'}`}>{POST_STATE[next.state]?.text ?? next.state}</span></>}
          </p>
          <ol className="dash-slots" aria-label="คิวโพสต์ถัดไป">
            {upcoming.slice(0, 4).map((p, i) => (
              <li key={p.id} className={i === 0 ? 'now' : ''}>
                <b>{timeFmt.format(new Date(p.scheduled_at))}</b>
                <span>{dayLabel(p.scheduled_at, now)}</span>
                <span className="muted">คลิป {p.clip_index}</span>
              </li>
            ))}
          </ol>
          <Link to="/schedule" className="dash-more">ดูตารางโพสต์ทั้งหมด</Link>
        </>
      )}
    </section>
  )
}

function QuotaCard() {
  const sub = useLoad<Subscription>('/v1/billing/subscription')
  const q = sub.data?.quota
  const pct = q && q.limit > 0 ? Math.min(100, Math.round((q.used / q.limit) * 100)) : 0
  return (
    <section className="card dash-card dash-small" aria-labelledby="dash-quota-title">
      <h2 id="dash-quota-title" className="dash-label">โควตาคลิปรอบนี้</h2>
      {sub.error && <Alert kind="error">{sub.error}</Alert>}
      {q && sub.data && (
        <>
          <p className="dash-big" data-testid="dash-quota">{q.used}<span className="dash-big-sub"> / {q.limit} คลิป</span></p>
          <div className="dash-meter" role="progressbar" aria-label="ใช้โควตาไปแล้ว" aria-valuemin={0} aria-valuemax={q.limit} aria-valuenow={q.used}>
            <i style={{ width: `${pct}%` }} />
          </div>
          <p className="dash-sub">เหลือ {q.available} · รอบนี้ถึง {dateFmt.format(new Date(q.cycle_end))}</p>
          <p className="dash-sub">
            {sub.data.status === 'trial' ? <span className="badge badge-active">ทดลองใช้</span> : sub.data.status === 'expired'
              ? <span className="badge badge-revoked">หมดอายุ</span> : <span className="badge badge-online">{sub.data.plan.name}</span>}
            {' '}<Link to="/billing">แพ็กเกจ</Link>
          </p>
        </>
      )}
    </section>
  )
}

function PhonesCard() {
  const devs = useLoad<{ items: Device[] }>('/v1/devices')
  const bound = (devs.data?.items ?? []).filter((d) => !d.unbound_at)
  const ready = bound.filter((d) => d.readiness === 'ready').length
  const needDetails = bound.filter((d) => d.missing_details.length > 0).length
  return (
    <section className="card dash-card dash-small" aria-labelledby="dash-phones-title">
      <h2 id="dash-phones-title" className="dash-label">โทรศัพท์</h2>
      {devs.error && <Alert kind="error">{devs.error}</Alert>}
      {devs.data && (
        bound.length === 0 ? (
          <div className="dash-empty">
            <p>ยังไม่มีโทรศัพท์</p>
            <p className="muted">เสียบโทรศัพท์กับเครื่องที่ติดตั้ง Agent แล้วระบบจะลงทะเบียนให้</p>
            <Link to="/devices" className="btn btn-secondary btn-small">ดูวิธีเพิ่มโทรศัพท์</Link>
          </div>
        ) : (
          <>
            <p className="dash-big" data-testid="dash-phones">{ready}<span className="dash-big-sub"> / {bound.length} พร้อมใช้งาน</span></p>
            {needDetails > 0 && <p className="dash-sub"><span className="badge badge-warn">ต้องใส่รายละเอียด {needDetails} เครื่อง</span></p>}
            <Link to="/devices" className="dash-more">จัดการโทรศัพท์</Link>
          </>
        )
      )}
    </section>
  )
}

function AttentionCard() {
  const att = useLoad<{ items: Post[] }>('/v1/schedule-items?attention=true')
  const n = att.data?.items.length ?? 0
  return (
    <section className={`card dash-card dash-small${n > 0 ? ' attention' : ''}`} aria-labelledby="dash-att-title">
      <h2 id="dash-att-title" className="dash-label">รอคุณตัดสินใจ</h2>
      {att.error && <Alert kind="error">{att.error}</Alert>}
      {att.data && (n === 0 ? (
        <p className="dash-sub">ไม่มีโพสต์ที่รอคุณ</p>
      ) : (
        <>
          <p className="dash-big" data-testid="dash-attention">{n}<span className="dash-big-sub"> โพสต์</span></p>
          <p className="dash-sub">เช่น ไม่ทราบผลโพสต์ หรือข้อความเปลี่ยนหลังตั้งเวลา</p>
          <Link to="/schedule" className="btn btn-secondary btn-small">ตรวจและจัดการ</Link>
        </>
      ))}
    </section>
  )
}

function RecentJobs() {
  const jobs = useLoad<{ items: Job[] }>('/v1/jobs')
  const items = (jobs.data?.items ?? []).slice(0, 5)
  return (
    <section className="card dash-card dash-wide" aria-labelledby="dash-jobs-title">
      <div className="card-head"><h2 id="dash-jobs-title" className="dash-label">งานล่าสุด</h2><Link to="/jobs" className="dash-more dash-head-link">ดูทั้งหมด</Link></div>
      {jobs.error && <Alert kind="error">{jobs.error}</Alert>}
      {jobs.data && items.length === 0 && (
        <div className="dash-empty">
          <p>ยังไม่มีงาน</p>
          <Link to="/create" className="btn btn-primary btn-small">สร้างงานแรก</Link>
        </div>
      )}
      {items.length > 0 && (
        <ul className="rows">
          {items.map((j) => (
            <li key={j.id} className="row" data-testid="dash-job">
              <div className="row-main">
                <Link to={`/jobs/${j.id}`} className="row-title dash-job-link">{sourceLabel(j)}</Link>
                <span className="hint">{j.planned_clips ?? (j.auto_clips ? 'ตามต้นฉบับ' : j.requested_clips)} คลิป · {dateFmt.format(new Date(j.created_at))}</span>
              </div>
              <span className={`badge badge-${JOB_STATE[j.state].badge}`}>{JOB_STATE[j.state].text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function AccountCard({ me }: { me: Me }) {
  return (
    <section className="card dash-card dash-small" aria-labelledby="ws-title">
      <h2 id="ws-title" className="dash-label">{me.workspace.name}</h2>
      <dl className="facts dash-facts">
        <dt>ผู้ใช้</dt><dd data-testid="me-username">{me.user.username}</dd>
        <dt>อีเมล</dt><dd data-testid="me-email">{me.user.email}</dd>
        <dt>บทบาท</dt><dd>{me.role === 'owner' ? 'เจ้าของ' : me.role}</dd>
        <dt>เขตเวลา</dt><dd>{me.workspace.timezone}</dd>
        <dt>คำรับรองสิทธิ์</dt>
        <dd>{me.rights_declaration ? `ยอมรับแล้ว (ฉบับ ${me.rights_declaration.version})` : 'ยังไม่ยอมรับ'}</dd>
      </dl>
    </section>
  )
}

export function HomePage() {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  useEffect(() => {
    let alive = true
    api<Me>('/v1/me').then((m) => alive && setMe(m)).catch((e: ApiError) => alive && setError(e))
    return () => { alive = false }
  }, [])

  if (error?.code === 'ONBOARDING_REQUIRED') return <Navigate to="/onboarding" replace />

  return (
    <Shell title="แดชบอร์ด" actions={<Link to="/create" className="btn btn-primary">สร้างงานใหม่</Link>}>
      {error && <Alert kind="error">{error.message}</Alert>}
      {!me && !error && <p className="muted" role="status">กำลังโหลด…</p>}
      {me && (
        <div className="dash">
          <NextPost />
          <QuotaCard />
          <PhonesCard />
          <RecentJobs />
          <AttentionCard />
          <AccountCard me={me} />
        </div>
      )}
    </Shell>
  )
}
