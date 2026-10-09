import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api, type Me } from '../lib/api'
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

/** E-50: the double-click setup, when the operator has published one. */
type Download = { available: false } | { available: true; version: string; url: string; sha256: string; size_mb: number | null }

const PRESENCE: Record<Agent['presence'], string> = { online: 'ออนไลน์', stale: 'ขาดการติดต่อ', offline: 'ออฟไลน์' }

export function AgentsPage() {
  const [items, setItems] = useState<Agent[] | null>(null)
  const [error, setError] = useState('')
  const [target, setTarget] = useState<Agent | null>(null)
  const [busy, setBusy] = useState(false)
  const [download, setDownload] = useState<Download | null>(null)
  const [username, setUsername] = useState('')

  useEffect(() => {
    api<Download>('/v1/agents/download').then(setDownload).catch(() => setDownload({ available: false }))
    api<Me>('/v1/me').then((me) => setUsername(me.user.username)).catch(() => undefined)
  }, [])

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
      <section className="card" aria-labelledby="install-title" data-testid="agent-install">
        <h2 id="install-title">ติดตั้ง Agent บน Windows</h2>
        <p className="muted">
          Agent ทำงานบน PC ของคุณ: ตัดคลิปบนเครื่องนี้ เก็บไฟล์ไว้ในโฟลเดอร์ที่เลือก และโพสต์ผ่านโทรศัพท์ที่เสียบ USB
        </p>
        {download === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {download?.available === true && (
          <div className="download">
            <a className="btn btn-primary" href={download.url} download>
              ดาวน์โหลด Agent {download.version}{download.size_mb ? ` (${download.size_mb} MB)` : ''}
            </a>
            <p className="muted">
              SHA-256 ของไฟล์: <code className="hash" data-testid="setup-sha256">{download.sha256}</code>
            </p>
          </div>
        )}
        {download?.available === false && (
          <Alert kind="info">ยังไม่เปิดให้ดาวน์โหลด ติดต่อทีมงาน punpun เพื่อรับไฟล์ติดตั้ง</Alert>
        )}
        <ol className="steps">
          <li>ดับเบิลคลิกไฟล์ที่ดาวน์โหลด ถ้า Windows ขึ้นว่า "Windows protected your PC" ให้กด More info แล้ว Run anyway</li>
          <li>
            ใส่ username {username ? <code>{username}</code> : 'ของคุณ'} และวาง Agent Token
            (สร้างได้ที่ <Link to="/agent-tokens">Agent Token</Link> แสดงครั้งเดียว)
          </li>
          <li>เลือกโฟลเดอร์เก็บคลิปในไดรฟ์ที่มีที่ว่างมาก เช่น <code>D:\punpun\clips</code> (Agent จะไม่รับงานใหม่ถ้าเหลือไม่ถึง 5 GB)</li>
          <li>เสียบโทรศัพท์ Android ทาง USB เปิด USB debugging และ login TikTok ไว้ในโทรศัพท์</li>
          <li>ดับเบิลคลิก <strong>punpun Agent</strong> บนหน้าจอ desktop แล้วเปิดหน้าต่างทิ้งไว้ระหว่างทำงาน</li>
        </ol>
      </section>
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
