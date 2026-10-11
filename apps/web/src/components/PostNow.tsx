/** "โพสต์ทันที" on an approved clip (PO 2026-10-10): pick a phone, confirm, and the Agent takes it on
 * its next check (within about 15 s). The server sets the time and runs every check of a scheduled post;
 * without a posting grant for the phone's account (Q-42) the Agent stops before pressing Post. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { ConfirmDialog } from './ConfirmDialog'
import { Alert } from './ui'

type Phone = { id: string; display_name: string | null; model: string | null; expected_account: string | null
  environment: { id: string }; unbound_at: string | null }

export function PostNow({ clipId, environmentId, onDone }: { clipId: string; environmentId: string; onDone?: () => void }) {
  const [open, setOpen] = useState(false)
  const [phones, setPhones] = useState<Phone[] | null>(null)
  const [deviceId, setDeviceId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  useEffect(() => {
    if (!open || phones) return
    api<{ items: Phone[] }>('/v1/devices').then(({ items }) => {
      const usable = items.filter((p) => !p.unbound_at && p.environment.id === environmentId && p.expected_account)
      setPhones(usable)
      setDeviceId(usable[0]?.id ?? '')
    }).catch((err: ApiError) => setError(err.message))
  }, [open, phones, environmentId])

  async function go() {
    setBusy(true)
    setError('')
    try {
      const out = await api<{ posting_mode: string }>(`/v1/clips/${clipId}/post-now`, {
        method: 'POST', body: { device_id: deviceId, idempotency_key: crypto.randomUUID().replace(/-/g, '') },
      })
      setOpen(false)
      setDone(out.posting_mode === 'live'
        ? 'ส่งให้ Agent แล้ว บัญชีนี้มีสิทธิ์โพสต์จริง (แบบเฉพาะฉัน) จะเริ่มภายในไม่กี่วินาที'
        : 'ส่งให้ Agent แล้ว (โหมดทดสอบ: Agent ส่งคลิปเข้าโทรศัพท์แล้วหยุดก่อนกดโพสต์)')
      onDone?.()
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button type="button" className="btn btn-secondary" onClick={() => { setDone(''); setOpen(true) }}>โพสต์ทันที</button>
      {done && <Alert kind="success">{done} — ดูผลที่ <Link to="/schedule">ตารางโพสต์</Link></Alert>}
      <ConfirmDialog open={open} busy={busy} title="โพสต์คลิปนี้ทันที?" confirmLabel="โพสต์ทันที"
        confirmDisabled={!deviceId} onConfirm={go} onCancel={() => setOpen(false)}>
        {error && <Alert kind="error">{error}</Alert>}
        {phones === null && !error && <p className="muted" role="status">กำลังโหลดโทรศัพท์…</p>}
        {phones?.length === 0 && (
          <p>ยังไม่มีโทรศัพท์ที่พร้อม ผูกโทรศัพท์และใส่บัญชี TikTok ที่ <Link to="/devices">หน้าโทรศัพท์</Link> ก่อน</p>
        )}
        {phones && phones.length > 0 && (
          <div className="field">
            <label htmlFor={`post-now-${clipId}`}>โพสต์ด้วยโทรศัพท์</label>
            <select id={`post-now-${clipId}`} value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
              {phones.map((p) => <option key={p.id} value={p.id}>{p.display_name ?? p.model ?? 'โทรศัพท์'} • @{p.expected_account}</option>)}
            </select>
          </div>
        )}
        <p className="muted">Agent จะเริ่มภายในไม่กี่วินาที ถ้าโทรศัพท์กำลังโพสต์คลิปอื่นอยู่จะต่อคิวหลังจากนั้น
          ใช้ข้อความเวอร์ชันที่อนุมัติแล้วเท่านั้น</p>
      </ConfirmDialog>
    </>
  )
}
