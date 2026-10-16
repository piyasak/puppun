/** Screen checks of one phone (PO 2026-10-16): ask the Agent for read-only screenshots of TikTok, and see
 * what the phone showed when a post stopped. Screenshots can show personal data: they are kept 7 days,
 * shown only to this Workspace and platform staff, and every opening is recorded. */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'
import { Alert } from './ui'

type DiagFile = { step: number; name: string; kind: 'png' | 'xml'; url?: string }
type Diagnostic = {
  id: string; kind: 'failure' | 'on_request'; check: string | null; check_label: string | null; code: string | null
  status: 'requested' | 'running' | 'done' | 'failed'; note: string | null; created_at: string; expires_at: string
  item_id: string | null; files: DiagFile[]
}
type Check = { check: string; label: string }

const STATUS: Record<Diagnostic['status'], string> = { requested: 'รอ Agent', running: 'กำลังตรวจ', done: 'เสร็จ', failed: 'หยุดกลางทาง' }
const STEP: Record<string, string> = {
  profile: 'โปรไฟล์', videos_tab: 'แท็บวิดีโอ', private_tab: 'แท็บส่วนตัว', newest_video: 'วิดีโอล่าสุด', stopped: 'หน้าจอตอนหยุด',
}

export function DeviceDiagnostics({ deviceId }: { deviceId: string }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Diagnostic[]>([])
  const [checks, setChecks] = useState<Check[]>([])
  const [check, setCheck] = useState('newest_public_video')
  const [shown, setShown] = useState<Diagnostic | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setItems((await api<{ items: Diagnostic[] }>(`/v1/devices/${deviceId}/diagnostics`)).items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [deviceId])

  useEffect(() => {
    if (!open) return
    void load()
    api<{ items: Check[] }>('/v1/diagnostics/checks').then((r) => setChecks(r.items)).catch(() => undefined)
    const timer = window.setInterval(() => void load(), 10000)
    return () => window.clearInterval(timer)
  }, [open, load])

  async function ask() {
    setError('')
    try {
      await api(`/v1/devices/${deviceId}/diagnostics`, { method: 'POST', body: { check } })
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function view(id: string) {
    setError('')
    try {
      setShown(await api<Diagnostic>(`/v1/diagnostics/${id}`))
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  if (!open) {
    return <button type="button" className="btn btn-secondary" onClick={() => setOpen(true)}>ตรวจหน้าจอ</button>
  }
  return (
    <div className="diagnostics" data-testid="device-diagnostics">
      <p className="hint">Agent เปิด TikTok ดูอย่างเดียว (ไม่พิมพ์ ไม่โพสต์) เมื่อโทรศัพท์ว่าง แล้วส่งภาพหน้าจอมา • เก็บ 7 วัน เห็นเฉพาะ Workspace นี้และผู้ดูแลระบบ</p>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="admin-action">
        <select aria-label="ตรวจอะไร" value={check} onChange={(e) => setCheck(e.target.value)}>
          {checks.map((c) => <option key={c.check} value={c.check}>{c.label}</option>)}
        </select>
        <button type="button" className="btn btn-secondary btn-small" onClick={() => void ask()}>ขอตรวจ</button>
        <button type="button" className="btn btn-small" onClick={() => { setOpen(false); setShown(null) }}>ปิด</button>
      </div>
      <ul className="rows">{items.map((d) => (
        <li key={d.id} className="row"><div className="row-main">
          <strong>{d.kind === 'failure' ? `หยุดตอนโพสต์ (${d.code ?? '—'})` : d.check_label ?? d.check} • {STATUS[d.status]}</strong>
          <span className="muted">{formatDate(d.created_at)}{d.note ? ` • ${d.note}` : ''} • ลบอัตโนมัติ {formatDate(d.expires_at)}</span>
        </div>
        {d.files.length > 0 && <button type="button" className="btn btn-secondary btn-small" onClick={() => void view(d.id)}>ดู</button>}
        </li>
      ))}</ul>
      {items.length === 0 && <p className="muted">ยังไม่มีการตรวจ</p>}
      {shown && (
        <div className="diagnostic-view" data-testid="diagnostic-view">
          {[...new Set(shown.files.map((f) => f.step))].map((step) => {
            const png = shown.files.find((f) => f.step === step && f.kind === 'png')
            const xml = shown.files.find((f) => f.step === step && f.kind === 'xml')
            const name = (png ?? xml)?.name ?? ''
            return (
              <figure key={step}>
                {png?.url && <img src={png.url} alt={`หน้าจอ: ${STEP[name] ?? name}`} style={{ maxWidth: 240, border: '1px solid var(--border, #ccc)' }} />}
                <figcaption>{STEP[name] ?? name}{xml?.url && <> • <a href={xml.url} target="_blank" rel="noreferrer">สิ่งที่ Agent อ่านได้ (XML)</a></>}</figcaption>
              </figure>
            )
          })}
        </div>
      )}
    </div>
  )
}
