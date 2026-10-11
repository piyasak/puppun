import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Shell } from '../components/Shell'
import { PostingGrants } from '../components/PostingGrants'
import { Alert, Field } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'

type Device = {
  id: string
  serial: string
  model: string | null
  android_version: string | null
  thai_keyboard: boolean | null
  display_name: string | null
  expected_account: string | null
  environment: { id: string; name: string }
  readiness: 'ready' | 'unauthorized' | 'offline' | 'missing' | 'agent_offline' | 'unknown' | 'unbound'
  last_reported_at: string | null
  unbound_at: string | null
  missing_details: ('display_name' | 'expected_account')[]
}

const READINESS: Record<Device['readiness'], { text: string; badge: string; help?: string }> = {
  ready: { text: 'พร้อมใช้งาน', badge: 'online' },
  unauthorized: { text: 'ยังไม่อนุญาต USB debugging', badge: 'stale', help: 'ปลดล็อกโทรศัพท์แล้วกด "อนุญาต" ที่หน้าจอ' },
  offline: { text: 'ADB ออฟไลน์', badge: 'stale', help: 'ถอดสาย USB แล้วเสียบใหม่ หรือรีสตาร์ทโทรศัพท์' },
  missing: { text: 'ไม่พบเครื่อง', badge: 'offline', help: 'ตรวจสาย USB ระหว่างโทรศัพท์กับเครื่อง Windows' },
  agent_offline: { text: 'Agent ออฟไลน์', badge: 'offline', help: 'เปิดโปรแกรม Agent บนเครื่อง Windows' },
  unknown: { text: 'ยังไม่มีรายงาน', badge: 'offline' },
  unbound: { text: 'ยกเลิกการผูกแล้ว', badge: 'revoked' },
}

function EditDevice({ device, onSaved, onCancel }: { device: Device; onSaved: () => void; onCancel: () => void }) {
  const [name, setName] = useState(device.display_name ?? '')
  const [account, setAccount] = useState(device.expected_account ? `@${device.expected_account}` : '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api(`/v1/devices/${device.id}`, { method: 'PATCH', body: { display_name: name, expected_account: account } })
      onSaved()
    } catch (err) {
      const ae = err as ApiError
      setError(ae.code === 'VALIDATION_ERROR' ? 'ชื่อบัญชี TikTok ใช้ได้เฉพาะ a-z, 0-9, _ และ . ยาว 2–24 ตัว' : ae.message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="limits-form">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="grid-3">
        <Field label="ชื่อเรียกเครื่อง" value={name} onChange={(e) => setName(e.target.value)} hint="เช่น POCO หน้าร้าน" />
        <Field label="บัญชี TikTok ที่ต้องโพสต์" value={account} onChange={(e) => setAccount(e.target.value)}
          hint="Agent ตรวจว่าบัญชีบนเครื่องตรงก่อนโพสต์ทุกครั้ง" placeholder="@username" />
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>ยกเลิก</button>
        <button type="submit" className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? 'กำลังบันทึก…' : 'บันทึก'}</button>
      </div>
    </form>
  )
}

export function DevicesPage() {
  const [items, setItems] = useState<Device[] | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [target, setTarget] = useState<Device | null>(null)
  const [busy, setBusy] = useState(false)
  // The Agent links here after registering a phone: /devices?edit=<id> opens its form (Q-25).
  const [params, setParams] = useSearchParams()

  const load = useCallback(async () => {
    try {
      const list = (await api<{ items: Device[] }>('/v1/devices')).items
      setItems(list)
      const wanted = params.get('edit')
      if (wanted && list.some((d) => d.id === wanted && !d.unbound_at)) {
        setEditing(wanted)
        setParams({}, { replace: true })
      }
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [params, setParams])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    return () => window.clearInterval(timer)
  }, [load])

  async function unbind() {
    if (!target) return
    setBusy(true)
    try {
      await api(`/v1/devices/${target.id}/unbind`, { method: 'POST' })
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
    <Shell title="โทรศัพท์">
      {error && <Alert kind="error">{error}</Alert>}
      <PostingGrants />
      <section className="card" aria-labelledby="devices-title">
        <h2 id="devices-title">โทรศัพท์ที่ผูกไว้</h2>
        <p className="muted">
          เสียบโทรศัพท์กับเครื่อง Windows ที่ติดตั้ง Agent แล้วเปิด USB debugging Agent จะลงทะเบียนเครื่องที่พร้อมให้อัตโนมัติ
          โทรศัพท์ที่ผูกกับบัญชีอื่นอยู่จะผูกซ้ำไม่ได้
        </p>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {items?.length === 0 && <p className="muted">ยังไม่มีโทรศัพท์</p>}
        <ul className="rows">
          {items?.map((d) => {
            const r = READINESS[d.readiness]
            return (
              <li key={d.id} className="row" data-testid="device-row">
                {editing === d.id ? (
                  <EditDevice device={d} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); void load() }} />
                ) : (
                  <>
                    <div className="row-main">
                      <strong>{d.display_name || d.model || d.serial}</strong>
                      <span className={`badge badge-${r.badge}`}>{r.text}</span>
                      {d.missing_details.length > 0 && (
                        <span className="badge badge-warn" data-testid="needs-details">
                          ต้องใส่รายละเอียด: {d.missing_details.map((m) => (m === 'expected_account' ? 'บัญชี TikTok' : 'ชื่อเรียกเครื่อง')).join(', ')}
                        </span>
                      )}
                      {d.thai_keyboard === false && d.readiness !== 'unbound' && (
                        <span className="badge badge-warn" data-testid="no-thai-keyboard">
                          ยังไม่มีคีย์บอร์ดพิมพ์ไทย: โพสต์จริงไม่ได้
                        </span>
                      )}
                      <span className="muted">
                        {d.model ?? '—'} • Android {d.android_version ?? '—'} • <code>{d.serial}</code> • {d.environment.name}
                      </span>
                      <span className="muted">
                        บัญชี TikTok: {d.expected_account ? `@${d.expected_account}` : 'ยังไม่กำหนด'} • รายงานล่าสุด {formatDate(d.last_reported_at)}
                      </span>
                      {r.help && d.readiness !== 'unbound' && <span className="hint">{r.help}</span>}
                      {d.thai_keyboard === false && d.readiness !== 'unbound' && (
                        <span className="hint">
                          เปิดหน้าต่างตั้งค่า punpun Agent บนเครื่อง Windows แล้วกด "ติดตั้งคีย์บอร์ดพิมพ์ไทย" (punpun Thai input)
                        </span>
                      )}
                    </div>
                    {d.readiness !== 'unbound' && (
                      <div className="row-actions">
                        <button type="button" className="btn btn-secondary" onClick={() => setEditing(d.id)}>แก้ไข</button>
                        <button type="button" className="btn btn-danger-outline" onClick={() => setTarget(d)}>ยกเลิกการผูก</button>
                      </div>
                    )}
                  </>
                )}
              </li>
            )
          })}
        </ul>
      </section>
      <ConfirmDialog open={target !== null} busy={busy} danger title="ยกเลิกการผูกโทรศัพท์นี้?"
        confirmLabel="ยกเลิกการผูก" onConfirm={unbind} onCancel={() => setTarget(null)}>
        <p>โทรศัพท์ {target?.display_name || target?.model} จะไม่รับงานโพสต์จากบัญชีนี้อีก และคืนโควตา 1 เครื่อง
          ถ้าจะใช้อีกต้องลงทะเบียนใหม่ผ่าน Agent (ยังไม่มีงานตั้งเวลาในระบบที่ได้รับผลกระทบ)</p>
      </ConfirmDialog>
    </Shell>
  )
}
