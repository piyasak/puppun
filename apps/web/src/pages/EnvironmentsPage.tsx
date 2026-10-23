import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Shell } from '../components/Shell'
import { Alert, Field } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { LIMIT_LABELS, type Environment, type Limits, type Usage } from '../lib/types'

const KEYS = Object.keys(LIMIT_LABELS) as (keyof Limits)[]

function limitError(e: ApiError): string {
  if (e.code === 'PLAN_LIMIT_EXCEEDED') return 'เกินจำนวนที่แพ็กเกจอนุญาต เมื่อรวมกับ Environment อื่นทั้งหมด'
  if (e.code === 'NAME_TAKEN') return 'มี Environment ชื่อนี้แล้ว'
  if (e.code === 'LIMIT_BELOW_USAGE') return 'ตั้งค่าต่ำกว่าที่ใช้อยู่ไม่ได้ ยกเลิกทะเบียน Agent หรือยกเลิกการผูกโทรศัพท์ที่ไม่ใช้ก่อน'
  if (e.code === 'VALIDATION_ERROR') return 'Session พร้อมกันต้องไม่เกินจำนวน Agent และทุกค่าต้องไม่ติดลบ'
  return e.message
}

function UsageCard({ usage }: { usage: Usage }) {
  return (
    <section className="card" aria-labelledby="usage-title">
      <div className="card-head">
        <h2 id="usage-title">แพ็กเกจ: {usage.plan.name}</h2>
        {usage.plan.is_demo && <span className="badge badge-warn">Demo</span>}
      </div>
      <p className="muted">ขีดจำกัดเป็นของทั้ง Workspace — การสร้าง Environment เพิ่มไม่ได้เพิ่มสิทธิ์</p>
      <div className="meters">
        {KEYS.map((k) => (
          <div key={k} className="meter">
            <span className="meter-label">{LIMIT_LABELS[k]}</span>
            <span className="meter-value" data-testid={`usage-${k}`}>{usage.allocated[k]} / {usage.caps[k]}</span>
            <progress max={usage.caps[k] || 1} value={usage.allocated[k]} aria-label={`${LIMIT_LABELS[k]} ที่จัดสรรแล้ว`} />
            <span className="hint" data-testid={`inuse-${k}`}>ใช้อยู่ {usage.in_use[k]}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function LimitsForm({ initial, submitLabel, onSubmit, onCancel }: {
  initial: { name: string } & Limits
  submitLabel: string
  onSubmit: (v: { name: string } & Limits) => Promise<void>
  onCancel?: () => void
}) {
  const [v, setV] = useState(initial)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (v.concurrent_session_limit > v.registered_agent_limit) {
      setError('Session พร้อมกันต้องไม่เกินจำนวน Agent ที่ลงทะเบียนได้')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit(v)
    } catch (err) {
      setError(limitError(err as ApiError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="limits-form">
      {error && <Alert kind="error">{error}</Alert>}
      <Field label="ชื่อ Environment" required value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })}
        hint="เช่น สำนักงาน, บ้าน" />
      <div className="grid-3">
        {KEYS.map((k) => (
          <Field key={k} label={LIMIT_LABELS[k]} type="number" min={0} inputMode="numeric" value={String(v[k])}
            onChange={(e) => setV({ ...v, [k]: Math.max(0, Number(e.target.value) || 0) })} />
        ))}
      </div>
      <div className="form-actions">
        {onCancel && <button type="button" className="btn btn-secondary" onClick={onCancel}>ยกเลิก</button>}
        <button type="submit" className="btn btn-primary" disabled={busy || !v.name.trim()} aria-busy={busy}>
          {busy ? 'กำลังบันทึก…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

/** Q-54 (PO 2026-10-23): posts running at once on this Environment, at most its phones; lower = less risk. */
function ParallelCap({ env, onSaved }: { env: Environment; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState(String(env.max_parallel_posts ?? ''))
  const [error, setError] = useState('')
  const max = Math.max(env.device_limit, 1)

  async function save() {
    setError('')
    try {
      await api(`/v1/environments/${env.id}`, { method: 'PATCH', body: { max_parallel_posts: Number(value) || 0 } })
      await onSaved()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  return (
    <div className="admin-action" data-testid="parallel-cap">
      <label>
        โพสต์พร้อมกันสูงสุด{' '}
        <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={`โพสต์พร้อมกันสูงสุด ${env.name}`}>
          <option value="">ตามจำนวนโทรศัพท์ ({max})</option>
          {Array.from({ length: max }, (_, i) => i + 1).map((n) => <option key={n} value={String(n)}>{n} เครื่อง</option>)}
        </select>
      </label>
      <button type="button" className="btn btn-secondary btn-small" onClick={() => void save()}
        disabled={value === String(env.max_parallel_posts ?? '')}>บันทึก</button>
      <span className="muted">ตอนนี้ใช้ {env.parallel_posts_cap} • ตั้งน้อยลงเพื่อลดความเสี่ยง • Agent 0.10.0 ขึ้นไปตั้งในเครื่องได้อีกชั้น</span>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

export function EnvironmentsPage() {
  const [items, setItems] = useState<Environment[] | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [formKey, setFormKey] = useState(0)

  const load = useCallback(async () => {
    try {
      const [list, u] = await Promise.all([api<{ items: Environment[] }>('/v1/environments'), api<Usage>('/v1/workspace/usage')])
      setItems(list.items)
      setUsage(u)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <Shell title="Environments">
      {error && <Alert kind="error">{error}</Alert>}
      {usage && <UsageCard usage={usage} />}

      <section className="card" aria-labelledby="new-env-title">
        <h2 id="new-env-title">สร้าง Environment</h2>
        <LimitsForm key={formKey} submitLabel="สร้าง Environment"
          initial={{ name: '', registered_agent_limit: 1, concurrent_session_limit: 1, device_limit: 1 }}
          onSubmit={async (v) => {
            await api('/v1/environments', { method: 'POST', body: v })
            setFormKey((k) => k + 1)
            await load()
          }} />
      </section>

      <section className="card" aria-labelledby="env-list-title">
        <h2 id="env-list-title">Environment ทั้งหมด</h2>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {items?.length === 0 && <p className="muted">ยังไม่มี Environment</p>}
        <ul className="rows">
          {items?.map((env) => (
            <li key={env.id} className="row">
              {editing === env.id ? (
                <LimitsForm initial={env} submitLabel="บันทึก" onCancel={() => setEditing(null)}
                  onSubmit={async (v) => {
                    await api(`/v1/environments/${env.id}`, { method: 'PATCH', body: v })
                    setEditing(null)
                    await load()
                  }} />
              ) : (
                <>
                  <div className="row-main">
                    <strong>{env.name}</strong>
                    <span className="muted">
                      {KEYS.map((k) => `${LIMIT_LABELS[k]} ${env[k]}`).join(' • ')}
                    </span>
                    <ParallelCap env={env} onSaved={load} />
                  </div>
                  <button type="button" className="btn btn-secondary" onClick={() => setEditing(env.id)}
                    aria-label={`แก้ไข ${env.name}`}>แก้ไข</button>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
    </Shell>
  )
}
