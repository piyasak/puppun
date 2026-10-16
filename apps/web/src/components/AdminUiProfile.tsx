/** Admin: TikTok's words, ids, waits and retries for the Agent (Q-50, PO 2026-10-16). Every save is a new
 * version with a reason; Agents 0.7.0+ fetch it within an hour and check it again before use. Only the
 * settings that differ from the built-in values need to be written. What keeps posting safe (Post itself,
 * the never-press words, the caption check) is not here: a profile can only add never-press words. */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'
import { Alert } from './ui'

type Version = { version: number; body: Record<string, unknown>; reason: string; created_at: string | null }
type Shown = { current: Version | null; defaults: Record<string, unknown>; history: Version[] }

const MIN_REASON = 10

export function AdminUiProfile({ isAdmin }: { isAdmin: boolean }) {
  const [shown, setShown] = useState<Shown | null>(null)
  const [text, setText] = useState('{}')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const load = useCallback(async () => {
    try {
      const out = await api<Shown>('/v1/admin/ui-profile')
      setShown(out)
      setText(JSON.stringify(out.current?.body ?? {}, null, 2))
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])
  useEffect(() => { void load() }, [load])

  async function save() {
    setError('')
    setDone('')
    let body: unknown
    try {
      body = JSON.parse(text)
    } catch {
      setError('JSON ไม่ถูกต้อง ตรวจวงเล็บและเครื่องหมายคำพูด')
      return
    }
    setBusy(true)
    try {
      const out = await api<Version>('/v1/admin/ui-profile', { method: 'POST', body: { body, reason } })
      setDone(`บันทึกเวอร์ชัน ${out.version} แล้ว Agent จะใช้ภายใน 1 ชั่วโมง`)
      setReason('')
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-labelledby="ui-profile-title">
      <h2 id="ui-profile-title">ค่าหน้าจอ TikTok (Agent 0.7.0 ขึ้นไป)</h2>
      <p className="muted">
        คำบนปุ่ม แท็บ แบนเนอร์ เวลารอ และจำนวนครั้งที่ลองใหม่ เปลี่ยนได้ที่นี่โดยไม่ต้องออก Agent ใหม่ ใส่เฉพาะค่าที่ต่างจากค่าในตัว
        • ปุ่มโพสต์และคำที่ห้ามกดแก้ไม่ได้ (เพิ่มคำห้ามกดได้อย่างเดียว)
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {done && <Alert kind="success">{done}</Alert>}
      <p data-testid="ui-profile-current">
        {shown?.current ? `ใช้อยู่: เวอร์ชัน ${shown.current.version} (${formatDate(shown.current.created_at ?? '')}) • ${shown.current.reason}` : 'ใช้อยู่: ค่าในตัว Agent (ยังไม่มีเวอร์ชันที่บันทึก)'}
      </p>
      <label htmlFor="ui-profile-json">ค่าที่ต่างจากค่าในตัว (JSON)</label>
      <textarea id="ui-profile-json" rows={12} spellCheck={false} value={text} readOnly={!isAdmin}
        onChange={(e) => setText(e.target.value)} style={{ width: '100%', fontFamily: 'monospace' }} />
      {isAdmin && (
        <div className="admin-action">
          <input aria-label="เหตุผล: บันทึกค่าหน้าจอ TikTok" placeholder="เหตุผล (อย่างน้อย 10 ตัวอักษร จะถูกบันทึก)"
            value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className="btn btn-secondary btn-small" disabled={busy || reason.trim().length < MIN_REASON}
            onClick={() => void save()}>บันทึกเวอร์ชันใหม่</button>
        </div>
      )}
      <details>
        <summary>ค่าในตัว Agent (ใช้เมื่อไม่ได้กำหนด)</summary>
        <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(shown?.defaults ?? {}, null, 2)}</pre>
      </details>
      {shown && shown.history.length > 0 && (
        <details>
          <summary>เวอร์ชันก่อนหน้า</summary>
          <ul className="rows">{shown.history.map((h) => (
            <li key={h.version} className="row"><div className="row-main">
              <strong>เวอร์ชัน {h.version}</strong>
              <span className="muted">{formatDate(h.created_at ?? '')} • {h.reason}</span>
            </div></li>
          ))}</ul>
        </details>
      )}
    </section>
  )
}
