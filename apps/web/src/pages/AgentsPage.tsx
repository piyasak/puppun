import { useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'

type Agent = {
  id: string
  installation_id: string
  environment: { id: string; name: string }
  agent_version: string | null
  registered: boolean
  presence: 'online' | 'stale' | 'offline'
  last_seen_at: string | null
  created_at: string
  deregistered_at: string | null
}

const PRESENCE: Record<Agent['presence'], string> = { online: 'ออนไลน์', stale: 'ขาดการติดต่อ', offline: 'ออฟไลน์' }

export function AgentsPage() {
  const [items, setItems] = useState<Agent[] | null>(null)
  const [error, setError] = useState('')
  const [target, setTarget] = useState<Agent | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await api<{ items: Agent[] }>('/v1/agents')).items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15_000) // matches the Agent heartbeat
    return () => window.clearInterval(timer)
  }, [load])

  async function deregister() {
    if (!target) return
    setBusy(true)
    try {
      await api(`/v1/agents/${target.id}/deregister`, { method: 'POST' })
      setTarget(null)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
      setTarget(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title="Agent">
      {error && <Alert kind="error">{error}</Alert>}
      <section className="card" aria-labelledby="agents-title">
        <h2 id="agents-title">Agent ที่ลงทะเบียน</h2>
        <p className="muted">
          การติดตั้งแต่ละเครื่องนับ 1 ทะเบียน การเชื่อมต่อใหม่จากเครื่องเดิมไม่นับเพิ่ม
          ถ้าถอนการติดตั้งไปแล้ว ให้ยกเลิกทะเบียนเพื่อคืนโควตา
        </p>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {items?.length === 0 && <p className="muted">ยังไม่มี Agent เชื่อมต่อ — สร้าง Agent Token แล้วใส่ในโปรแกรม Agent บน Windows</p>}
        <ul className="rows">
          {items?.map((a) => (
            <li key={a.id} className="row" data-testid="agent-row">
              <div className="row-main">
                <strong>{a.environment.name}</strong>
                <span className={`badge badge-${a.registered ? a.presence : 'revoked'}`}>
                  {a.registered ? PRESENCE[a.presence] : 'ยกเลิกทะเบียนแล้ว'}
                </span>
                <span className="muted">
                  <code>{a.installation_id.slice(0, 8)}</code> • เวอร์ชัน {a.agent_version ?? '—'} • ติดต่อล่าสุด {formatDate(a.last_seen_at)}
                </span>
              </div>
              {a.registered && (
                <button type="button" className="btn btn-danger-outline" onClick={() => setTarget(a)}>ยกเลิกทะเบียน</button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <ConfirmDialog open={target !== null} busy={busy} danger title="ยกเลิกทะเบียน Agent นี้?"
        confirmLabel="ยกเลิกทะเบียน" onConfirm={deregister} onCancel={() => setTarget(null)}>
        <p>Agent นี้จะหยุดรับงานทันทีและคืน 1 ทะเบียนให้ Environment "{target?.environment.name}"
          ถ้าเครื่องนี้ยังใช้งานอยู่ จะต้องเชื่อมต่อใหม่ (นับทะเบียนใหม่)</p>
      </ConfirmDialog>
    </Shell>
  )
}
