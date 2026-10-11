import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import type { JobDetail } from '../lib/jobs'

/* P4.2: the schedule is always calculated on the server; the browser only shows the preview. */

type Device = {
  id: string; serial: string; model: string | null; display_name: string | null; expected_account: string | null
  environment: { id: string; name: string }; unbound_at: string | null
}
type PreviewItem = {
  seq: number; clip_index: number; metadata_version: number; scheduled_at: string; scheduled_local: string
  expected_start: string; expected_start_local: string; collides_with: string[]
}
type Preview = {
  items: PreviewItem[]; excluded: { index: number; reason: string }[]; collisions: number
  window: string; timezone: string; interval_hours: number
}
type Item = {
  id: string; seq: number; clip_index: number; state: string; reason: string | null; metadata_version: number; state_version: number
  scheduled_at: string; claimed_at: string | null; verified_at: string | null
}
type Series = {
  id: string; state: string; device: { name: string | null; account: string | null }; window: string
  timezone: string; interval_hours: number; offline_policy: 'defer' | 'skip'; items: Item[]; version: number
}
type Decision = 'found_published' | 'confirmed_not_published' | 'still_unknown'
const DECISIONS: { id: Decision; text: string; hint: string }[] = [
  { id: 'found_published', text: 'พบโพสต์แล้ว', hint: 'โพสต์ขึ้นในบัญชีที่ถูกต้อง — ใส่ลิงก์โพสต์เป็นหลักฐาน' },
  { id: 'confirmed_not_published', text: 'ยืนยันว่าไม่ได้โพสต์', hint: 'ตรวจทั้งโปรไฟล์และร่างแล้วไม่มี — ระบบจะโพสต์ใหม่ 1 ครั้งในช่วงเวลาที่อนุญาตถัดไป' },
  { id: 'still_unknown', text: 'ยังไม่แน่ใจ', hint: 'เก็บไว้เป็นไม่ทราบผล โทรศัพท์นี้จะยังไม่โพสต์ต่อ' },
]
const RETRYABLE = ['AGENT_LOST', 'ACCOUNT_MISMATCH', 'TRANSFER_FAILED', 'GALLERY_NOT_FOUND', 'FILE_UNAVAILABLE',
  'DOWNLOAD_FAILED', 'FILE_HASH_MISMATCH', 'DEVICE_NOT_CONNECTED', 'AGENT_ERROR', 'WIFI_OFFLINE',
  'ACCOUNT_UNREADABLE', 'THAI_KEYBOARD_MISSING']  // = posts.RETRYABLE_REASONS
type ResumePreview = { series_version: number; moves: { seq: number; from: string; to: string }[] }

function toLocalInput(iso: string): string {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(iso)).reduce<Record<string, string>>((acc, x) => ({ ...acc, [x.type]: x.value }), {})
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
}

const EDIT_ERRORS: Record<string, string> = {
  OUTSIDE_WINDOW: 'เวลาอยู่นอกช่วงที่โพสต์ได้', START_IN_PAST: 'เวลาต้องอยู่ในอนาคต',
  ITEM_ORDER: 'เวลาใหม่ต้องอยู่ระหว่างโพสต์ก่อนหน้าและถัดไป (คงลำดับคลิป)', VERSION_CONFLICT: 'รายการถูกเปลี่ยนไปแล้ว โหลดใหม่',
  ITEM_NOT_EDITABLE: 'รายการนี้เริ่มส่งแล้ว แก้ไม่ได้',
}

function ItemTimeEditor({ item, onDone }: { item: Item; onDone: (msg?: string) => void }) {
  const [value, setValue] = useState(toLocalInput(item.scheduled_at))
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try {
      await api(`/v1/schedule-items/${item.id}`, { method: 'PATCH', body: { expected_state_version: item.state_version, scheduled_local: value } })
      onDone()
    } catch (err) {
      const ae = err as ApiError
      onDone(EDIT_ERRORS[ae.code] ?? ae.message)
    }
  }
  return (
    <span className="inline-edit">
      <input type="datetime-local" aria-label={`เวลาใหม่ของโพสต์ ${item.seq}`} value={value} onChange={(e) => setValue(e.target.value)} />
      <button type="button" className="btn btn-primary btn-small" onClick={save} disabled={busy}>บันทึก</button>
      <button type="button" className="btn btn-secondary btn-small" onClick={() => onDone()} disabled={busy}>ยกเลิก</button>
    </span>
  )
}

const INTERVALS = [1, 2, 3, 6, 12, 24]
const HOURS = Array.from({ length: 25 }, (_, h) => `${String(h).padStart(2, '0')}:00`)
const EXCLUDED: Record<string, string> = {
  NOT_APPROVED: 'ยังไม่อนุมัติ', ALREADY_SCHEDULED: 'ตั้งเวลาไว้แล้ว', POST_NEEDS_ACTION: 'มีโพสต์ที่ต้องดำเนินการค้างอยู่', CHECKS_FAILED: 'ไม่ผ่านการตรวจไฟล์', NOT_UPLOADED: 'ยังไม่ได้รับไฟล์', FILE_DELETED: 'ลบไฟล์แล้วหลังโพสต์',
}
const ITEM_STATE: Record<string, { text: string; badge: string }> = {
  SCHEDULED: { text: 'รอเวลาโพสต์', badge: 'active' },
  NEEDS_ACTION: { text: 'ต้องดำเนินการ', badge: 'warn' },
  CANCELLED: { text: 'ยกเลิกแล้ว', badge: 'expired' },
  SKIPPED: { text: 'ข้ามแล้ว', badge: 'expired' },
  CLAIMED: { text: 'Agent รับงานแล้ว', badge: 'stale' },
  TRANSFERRING: { text: 'กำลังส่งไฟล์เข้าโทรศัพท์', badge: 'stale' },
  PREPARING: { text: 'กำลังเตรียมโพสต์', badge: 'stale' },
  SUBMITTING: { text: 'กำลังโพสต์', badge: 'stale' },
  VERIFYING: { text: 'กำลังตรวจผล', badge: 'stale' },
  VERIFIED_SUCCESS: { text: 'โพสต์สำเร็จ (ยืนยันแล้ว)', badge: 'online' },
  UNKNOWN: { text: 'ไม่ทราบผล', badge: 'revoked' },
  DRY_RUN_DONE: { text: 'ทดสอบเสร็จ (ไม่ได้โพสต์จริง)', badge: 'expired' },
}
const REASON: Record<string, string> = {
  FILE_UNAVAILABLE: 'ไฟล์คลิปไม่อยู่บนเครื่อง Agent ที่รับงาน — ถ้าย้ายโฟลเดอร์คลิปไปแล้ว กด "เริ่มงานใหม่" ด้านบน Agent จะหาไฟล์หรือทำใหม่ แล้วโพสต์นี้จะกลับไปรอเอง',
  APPROVAL_CHANGED: 'ข้อความเปลี่ยนหลังตั้งเวลา — อนุมัติข้อความล่าสุดของคลิปนี้เพื่อให้โพสต์ต่อ',
  DEVICE_UNBOUND: 'โทรศัพท์ถูกยกเลิกการผูก — ยกเลิกรายการนี้แล้วตั้งเวลาใหม่กับเครื่องอื่น',
  FILE_DELETED: 'ไฟล์คลิปถูกลบจากเครื่อง Agent แล้วหลังโพสต์สำเร็จ (ตั้งไว้ตอนสร้างงาน) โพสต์ซ้ำไม่ได้',
  NOT_APPROVED: 'คลิปนี้ยังไม่ได้อนุมัติเวอร์ชันล่าสุด — ตรวจและอนุมัติแล้วรายการจะกลับมารอโพสต์',
  AGENT_LOST: 'Agent หยุดตอบหลายครั้งก่อนเริ่มโพสต์ — ตรวจเครื่อง Windows แล้วตั้งเวลาใหม่',
  AGENT_LOST_AFTER_SUBMIT: 'Agent หายไปหลังกดโพสต์ จึงไม่รู้ว่าโพสต์ขึ้นหรือไม่ — ตรวจในแอป TikTok ก่อน ระบบจะไม่ลองโพสต์ซ้ำเอง',
  DEFERRED: 'เครื่องออฟไลน์ตอนถึงเวลา — เลื่อนออกไปโดยรักษาระยะห่างเดิม',
  RESOLVED_PUBLISHED: 'ยืนยันแล้วว่าโพสต์ขึ้น (ตรวจโดยผู้ใช้)',
  RESOLVED_NOT_PUBLISHED: 'ยืนยันแล้วว่าไม่ได้โพสต์ — จะโพสต์ใหม่ 1 ครั้ง',
  RETRY_REQUESTED: 'ลองใหม่ตามที่สั่ง',
  TRANSFER_FAILED: 'ส่งไฟล์เข้าโทรศัพท์ไม่สำเร็จ — ตรวจสาย USB แล้วกดลองใหม่',
  GALLERY_NOT_FOUND: 'โทรศัพท์ไม่แสดงไฟล์ใน Gallery — ตรวจพื้นที่และสิทธิ์ แล้วกดลองใหม่',
  MISSED_SLOT: 'เครื่องออฟไลน์ตอนถึงเวลา — ข้ามรอบนี้ตามที่ตั้งไว้',
  REDELIVERY: 'Agent ก่อนหน้าหยุดก่อนเริ่มโพสต์ — ส่งให้ทำใหม่',
  ACCOUNT_MISMATCH: 'บัญชี TikTok บนโทรศัพท์ไม่ตรงกับที่ตั้งไว้ — ระบบจึงไม่โพสต์',
}
const SERIES_STATE: Record<string, string> = { ACTIVE: 'กำลังใช้งาน', PAUSED: 'หยุดชั่วคราว', CANCELLED: 'ยกเลิกแล้ว', COMPLETED: 'ครบแล้ว' }

function when(iso: string, tz: string) {
  return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short', timeZone: tz }).format(new Date(iso))
}

function defaultStart(): string {
  // Next full hour, Bangkok wall-clock time (the MVP timezone).
  const d = new Date(Date.now() + 60 * 60 * 1000)
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' })
    .formatToParts(d).reduce<Record<string, string>>((acc, p) => ({ ...acc, [p.type]: p.value }), {})
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:00`
}

export function SchedulePanel({ job, refresh }: { job: JobDetail; refresh: string }) {
  const [devices, setDevices] = useState<Device[] | null>(null)
  const [series, setSeries] = useState<Series[]>([])
  const [error, setError] = useState('')
  const [deviceId, setDeviceId] = useState('')
  const [start, setStart] = useState(defaultStart)
  const [interval, setIntervalHours] = useState(2)
  const [winStart, setWinStart] = useState('09:00')
  const [winEnd, setWinEnd] = useState('21:00')
  const [policy, setPolicy] = useState<'defer' | 'skip'>('defer')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<Series | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [resumeFor, setResumeFor] = useState<{ series: Series; preview: ResumePreview } | null>(null)
  const [resolving, setResolving] = useState<Item | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [evidence, setEvidence] = useState('')
  // One key per previewed plan: a double click on "confirm" never makes two series.
  const [key, setKey] = useState(() => crypto.randomUUID().replace(/-/g, ''))

  const load = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([
        api<{ items: Device[] }>('/v1/devices'),
        api<{ items: Series[] }>(`/v1/schedules?job_id=${job.id}`),
      ])
      const usable = d.items.filter((x) => x.environment.id === job.environment_id && !x.unbound_at)
      setDevices(usable)
      setDeviceId((cur) => cur || usable.find((x) => x.expected_account)?.id || usable[0]?.id || '')
      setSeries(s.items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [job.id, job.environment_id])

  // `refresh` changes when a clip's text or approval changes: items may have been parked or rebound.
  useEffect(() => { void load() }, [load, refresh])

  const body = useMemo(() => ({
    job_id: job.id, device_id: deviceId, start_local: start, timezone: 'Asia/Bangkok',
    window_start: winStart, window_end: winEnd, interval_hours: interval, offline_policy: policy,
  }), [job.id, deviceId, start, winStart, winEnd, interval, policy])

  function changed<T>(set: (v: T) => void) {
    return (v: T) => { set(v); setPreview(null) }  // a stale preview is never confirmed
  }

  async function showPreview(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      setPreview(await api<Preview>('/v1/schedules/preview', { method: 'POST', body }))
      setKey(crypto.randomUUID().replace(/-/g, ''))
    } catch (err) {
      setPreview(null)
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await api('/v1/schedules', { method: 'POST', body: { ...body, idempotency_key: key } })
      setPreview(null)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  async function cancelItem(id: string) {
    try {
      await api(`/v1/schedule-items/${id}/cancel`, { method: 'POST' })
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function pause(s: Series) {
    try {
      await api(`/v1/schedules/${s.id}/pause`, { method: 'POST' })
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function askResume(s: Series) {
    try {
      setResumeFor({ series: s, preview: await api<ResumePreview>(`/v1/schedules/${s.id}/resume/preview`, { method: 'POST' }) })
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function resume() {
    if (!resumeFor) return
    setBusy(true)
    try {
      await api(`/v1/schedules/${resumeFor.series.id}/resume`, { method: 'POST', body: { expected_version: resumeFor.preview.series_version } })
      setResumeFor(null)
      await load()
    } catch (err) {
      setError((err as ApiError).code === 'VERSION_CONFLICT' ? 'ตารางเปลี่ยนไปแล้ว ลองดูผลอีกครั้ง' : (err as ApiError).message)
      setResumeFor(null)
    } finally {
      setBusy(false)
    }
  }

  function openResolve(it: Item) {
    setResolving(it)
    setDecision(null)  // never preselected (PRD §H)
    setEvidence('')
  }

  async function resolve() {
    if (!resolving || !decision) return
    setBusy(true)
    try {
      await api(`/v1/schedule-items/${resolving.id}/resolve`, {
        method: 'POST', body: { decision, evidence, expected_state_version: resolving.state_version },
      })
      setResolving(null)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
      setResolving(null)
    } finally {
      setBusy(false)
    }
  }

  async function retryItem(it: Item) {
    try {
      await api(`/v1/schedule-items/${it.id}/retry`, { method: 'POST', body: { expected_state_version: it.state_version } })
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function cancelSeries() {
    if (!cancelTarget) return
    setBusy(true)
    try {
      await api(`/v1/schedules/${cancelTarget.id}/cancel`, { method: 'POST' })
      setCancelTarget(null)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
      setCancelTarget(null)
    } finally {
      setBusy(false)
    }
  }

  const approved = job.clips.filter((c) => c.approval.approved).length
  const device = devices?.find((d) => d.id === deviceId)

  return (
    <section className="card" aria-labelledby="schedule-title">
      <h2 id="schedule-title">ตั้งเวลาโพสต์</h2>
      <p className="muted">โพสต์เฉพาะคลิปที่อนุมัติแล้ว ({approved} จาก {job.clips.length} คลิป) ตามข้อความเวอร์ชันที่อนุมัติ ถ้าแก้ข้อความภายหลัง รายการจะหยุดรอจนกว่าจะอนุมัติใหม่</p>
      {error && <Alert kind="error">{error}</Alert>}
      {devices?.length === 0 && (
        <Alert kind="info">ยังไม่มีโทรศัพท์ใน Environment นี้ — เสียบโทรศัพท์กับเครื่องที่ติดตั้ง Agent แล้วดูที่ <Link to="/devices">หน้าโทรศัพท์</Link></Alert>
      )}

      {devices && devices.length > 0 && (
        <form onSubmit={showPreview} noValidate>
          <div className="grid-3 grid-wide">
            <div className="field">
              <label htmlFor="sch-device">โทรศัพท์</label>
              <select id="sch-device" value={deviceId} onChange={(e) => changed(setDeviceId)(e.target.value)}>
                {devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name || d.model || d.serial}{d.expected_account ? ` (@${d.expected_account})` : ' — ยังไม่ใส่บัญชี TikTok'}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="sch-start">เริ่ม (เวลาประเทศไทย)</label>
              <input id="sch-start" type="datetime-local" value={start} onChange={(e) => changed(setStart)(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="sch-interval">โพสต์ทุก</label>
              <select id="sch-interval" value={interval} onChange={(e) => changed(setIntervalHours)(Number(e.target.value))}>
                {INTERVALS.map((h) => <option key={h} value={h}>{h} ชั่วโมง</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="sch-ws">ช่วงเวลาที่โพสต์ได้ เริ่ม</label>
              <select id="sch-ws" value={winStart} onChange={(e) => changed(setWinStart)(e.target.value)}>
                {HOURS.slice(0, 24).map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="sch-we">ถึง (ไม่รวม)</label>
              <select id="sch-we" value={winEnd} onChange={(e) => changed(setWinEnd)(e.target.value)}>
                {HOURS.slice(1).map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </div>
          </div>
          <fieldset className="choices">
            <legend>ถ้าโทรศัพท์ออฟไลน์ตอนถึงเวลา</legend>
            <label className="check"><input type="radio" name="policy" checked={policy === 'defer'} onChange={() => changed(setPolicy)('defer')} />
              <span>เลื่อนออกไป (รักษาระยะห่างเดิม ไม่โพสต์รวดเดียว)</span></label>
            <label className="check"><input type="radio" name="policy" checked={policy === 'skip'} onChange={() => changed(setPolicy)('skip')} />
              <span>ข้ามรอบนั้น</span></label>
          </fieldset>
          {device && !device.expected_account && (
            <Alert kind="info">โทรศัพท์นี้ยังไม่ได้ใส่บัญชี TikTok — <Link to={`/devices?edit=${device.id}`}>ใส่รายละเอียด</Link></Alert>
          )}
          <div className="form-actions">
            <button type="submit" className="btn btn-secondary" disabled={busy || !deviceId}>ดูตัวอย่างเวลา</button>
          </div>
        </form>
      )}

      {preview && (
        <div className="schedule-preview" data-testid="schedule-preview">
          <h3>ตัวอย่างจาก Server</h3>
          <p className="muted">ทุก {preview.interval_hours} ชั่วโมง • ช่วง {preview.window} • {preview.timezone}</p>
          <table className="table">
            <thead><tr><th>ลำดับ</th><th>คลิป</th><th>เวลานัด</th><th>หมายเหตุ</th></tr></thead>
            <tbody>
              {preview.items.map((it) => (
                <tr key={it.seq} data-testid="preview-row">
                  <td>{it.seq}</td>
                  <td>คลิป {it.clip_index} (ข้อความเวอร์ชัน {it.metadata_version})</td>
                  <td>{when(it.scheduled_at, preview.timezone)}</td>
                  <td>{it.collides_with.length > 0
                    ? `ชนกับโพสต์อื่นบนเครื่องนี้ — เข้าคิว คาดว่าเริ่ม ${when(it.expected_start, preview.timezone)}`
                    : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.excluded.length > 0 && (
            <p className="hint">ไม่รวม: {preview.excluded.map((x) => `คลิป ${x.index} (${EXCLUDED[x.reason] ?? x.reason})`).join(', ')}</p>
          )}
          <div className="form-actions">
            <button type="button" className="btn btn-primary" onClick={confirm} disabled={busy} aria-busy={busy}>
              {busy ? 'กำลังบันทึก…' : `ยืนยันตั้งเวลา ${preview.items.length} โพสต์`}
            </button>
          </div>
        </div>
      )}

      {series.length > 0 && (
        <div className="series-list">
          <h3>ตารางโพสต์ของงานนี้</h3>
          {series.map((s) => (
            <div key={s.id} className="series" data-testid="series">
              <div className="card-head">
                <strong>{s.device.name} (@{s.device.account})</strong>
                <span className={`badge badge-${s.state === 'ACTIVE' ? 'active' : 'expired'}`}>{SERIES_STATE[s.state] ?? s.state}</span>
                <span className="muted">ทุก {s.interval_hours} ชม. • {s.window} • ออฟไลน์: {s.offline_policy === 'defer' ? 'เลื่อน' : 'ข้าม'}</span>
                <span className="series-actions">
                  {s.state === 'ACTIVE' && (
                    <button type="button" className="btn btn-secondary btn-small" onClick={() => pause(s)}>หยุดชั่วคราว</button>
                  )}
                  {s.state === 'PAUSED' && (
                    <button type="button" className="btn btn-primary btn-small" onClick={() => askResume(s)}>ทำงานต่อ…</button>
                  )}
                  {(s.state === 'ACTIVE' || s.state === 'PAUSED') && (
                    <button type="button" className="btn btn-danger-outline btn-small" onClick={() => setCancelTarget(s)}>ยกเลิกทั้งตาราง</button>
                  )}
                </span>
              </div>
              <table className="table">
                <thead><tr><th>ลำดับ</th><th>คลิป</th><th>เวลานัด</th><th>สถานะ</th><th /></tr></thead>
                <tbody>
                  {s.items.map((it) => {
                    const st = ITEM_STATE[it.state] ?? { text: it.state, badge: 'stale' }
                    const pending = it.state === 'SCHEDULED' || it.state === 'NEEDS_ACTION'
                    return (
                      <tr key={it.id} data-testid="schedule-item">
                        <td>{it.seq}</td>
                        <td>คลิป {it.clip_index} (v{it.metadata_version})</td>
                        <td>
                          {editing === it.id
                            ? <ItemTimeEditor item={it} onDone={(msg) => { setEditing(null); setError(msg ?? ''); void load() }} />
                            : when(it.scheduled_at, s.timezone)}
                        </td>
                        <td>
                          <span className={`badge badge-${st.badge}`}>{st.text}</span>
                          {it.reason && REASON[it.reason] && <div className="hint">{REASON[it.reason]}</div>}
                        </td>
                        <td className="row-actions">
                          {pending && editing !== it.id && <button type="button" className="btn btn-secondary btn-small" onClick={() => setEditing(it.id)}>แก้เวลา</button>}
                          {pending && <button type="button" className="btn btn-secondary btn-small" onClick={() => cancelItem(it.id)}>ยกเลิก</button>}
                          {it.state === 'UNKNOWN' && <button type="button" className="btn btn-primary btn-small" onClick={() => openResolve(it)}>ยืนยันผล…</button>}
                          {it.state === 'NEEDS_ACTION' && it.reason && RETRYABLE.includes(it.reason) && (
                            <button type="button" className="btn btn-primary btn-small" onClick={() => retryItem(it)}>แก้แล้ว ลองใหม่</button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
      <ConfirmDialog open={resolving !== null} busy={busy} title={`ยืนยันผลโพสต์ ${resolving?.seq ?? ''}`} confirmLabel="บันทึกผล"
        confirmDisabled={!decision || evidence.trim().length < 5} onConfirm={resolve} onCancel={() => setResolving(null)}>
        <p>Agent หายไปหลังกดโพสต์ จึงไม่รู้ว่าโพสต์ขึ้นหรือไม่ เปิดแอป TikTok ของบัญชีนี้แล้วตรวจก่อนเลือก ระบบจะไม่โพสต์ซ้ำเองจนกว่าจะยืนยัน</p>
        <fieldset className="choices">
          <legend>ผลที่ตรวจพบ</legend>
          {DECISIONS.map((d) => (
            <label key={d.id} className="check">
              <input type="radio" name="decision" checked={decision === d.id} onChange={() => setDecision(d.id)} />
              <span>{d.text}<br /><span className="hint">{d.hint}</span></span>
            </label>
          ))}
        </fieldset>
        <div className="field">
          <label htmlFor="resolve-evidence">หลักฐาน</label>
          <textarea id="resolve-evidence" rows={2} maxLength={500} value={evidence} onChange={(e) => setEvidence(e.target.value)}
            placeholder="เช่น ลิงก์โพสต์ หรือสิ่งที่เห็นในแอป" />
        </div>
      </ConfirmDialog>
      <ConfirmDialog open={resumeFor !== null} busy={busy} title="ให้ตารางนี้ทำงานต่อ?" confirmLabel="ทำงานต่อ"
        onConfirm={resume} onCancel={() => setResumeFor(null)}>
        {resumeFor && resumeFor.preview.moves.length === 0 && <p>เวลาโพสต์ทั้งหมดยังไม่ผ่านไป ใช้เวลาเดิม</p>}
        {resumeFor && resumeFor.preview.moves.length > 0 && (
          <>
            <p>โพสต์ที่เลยเวลาระหว่างหยุดจะไม่ถูกโพสต์รวดเดียว แต่เลื่อนออกไปโดยรักษาระยะห่างเดิม (คำนวณจาก Server):</p>
            <ul data-testid="resume-moves">
              {resumeFor.preview.moves.map((m) => (
                <li key={m.seq}>โพสต์ {m.seq}: {when(m.from, resumeFor.series.timezone)} → {when(m.to, resumeFor.series.timezone)}</li>
              ))}
            </ul>
          </>
        )}
      </ConfirmDialog>
      <ConfirmDialog open={cancelTarget !== null} busy={busy} danger title="ยกเลิกตารางโพสต์นี้?" confirmLabel="ยกเลิกทั้งตาราง"
        onConfirm={cancelSeries} onCancel={() => setCancelTarget(null)}>
        <p>รายการที่ยังไม่เริ่มโพสต์จะถูกยกเลิกทั้งหมด คลิปจะกลับมาตั้งเวลาใหม่ได้</p>
      </ConfirmDialog>
    </section>
  )
}
