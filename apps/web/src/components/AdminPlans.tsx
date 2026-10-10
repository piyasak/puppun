/** Admin: set prices and limits, open or close a plan for sale, switch its Demo label (PO 2026-10-10).
 * A price/limit change makes a new version (customers keep what they paid for until renewal);
 * selling and the Demo label switch the latest version in place. Every change needs a reason. */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { baht, clipsLabel } from '../lib/plans'
import { Alert } from './ui'

export type AdminPlan = {
  code: string; version: number; name: string; price_satang: number; clips_per_month: number | null
  max_registered_agents: number; max_concurrent_sessions: number; max_devices: number; interval_days: number
  retention_days: number; is_purchasable: boolean; example: boolean
}

const MIN_REASON = 10

function latestByCode(rows: AdminPlan[]): AdminPlan[] {
  const latest = new Map<string, AdminPlan>()
  for (const p of rows) if (!latest.has(p.code) || p.version > latest.get(p.code)!.version) latest.set(p.code, p)
  return [...latest.values()].sort((a, b) => a.price_satang - b.price_satang)
}

function PlanEditor({ plan, isAdmin, onDone }: { plan: AdminPlan; isAdmin: boolean; onDone: (msg: string) => void }) {
  const [price, setPrice] = useState(String(plan.price_satang / 100))
  const [days, setDays] = useState(String(plan.interval_days))
  const [pcs, setPcs] = useState(String(plan.max_registered_agents))
  const [phones, setPhones] = useState(String(plan.max_devices))
  const [unlimited, setUnlimited] = useState(plan.clips_per_month === null)
  const [clips, setClips] = useState(String(plan.clips_per_month ?? 1000))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const trial = plan.code === 'trial'
  const id = `plan-${plan.code}`

  async function call(path: string, body: Record<string, unknown>, done: string) {
    setBusy(true)
    setError('')
    try {
      await api(path, { method: 'POST', body: { ...body, reason } })
      setReason('')
      onDone(done)
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  function saveVersion() {
    const pcsN = Math.trunc(Number(pcs))
    void call(`/v1/admin/plans/${plan.code}/versions`, {
      price_satang: Math.round(Number(price) * 100), interval_days: Math.trunc(Number(days)),
      max_registered_agents: pcsN, max_concurrent_sessions: pcsN, max_devices: Math.trunc(Number(phones)),
      ...(unlimited ? { unlimited_clips: true } : { clips_per_month: Math.trunc(Number(clips)) }),
    }, `${plan.code}: บันทึกเป็นเวอร์ชันใหม่แล้ว`)
  }

  const reasonOk = reason.trim().length >= MIN_REASON
  return (
    <article className="admin-plan" data-testid={id}>
      <header className="admin-plan-head">
        <h3>{plan.name} <span className="muted">({plan.code} v{plan.version})</span></h3>
        <span className={`badge badge-${trial ? 'active' : plan.is_purchasable ? 'online' : 'revoked'}`}>{trial ? 'ให้อัตโนมัติ' : plan.is_purchasable ? 'เปิดขาย' : 'ปิดขาย'}</span>
        {plan.example && <span className="badge badge-warn">Demo</span>}
      </header>
      <p className="muted">ตอนนี้: {baht(plan.price_satang)} / {plan.interval_days} วัน • PC {plan.max_registered_agents} • โทรศัพท์ {plan.max_devices} • {clipsLabel(plan.clips_per_month)}</p>
      {error && <Alert kind="error">{error}</Alert>}
      {isAdmin && (
        <>
          <div className="admin-plan-grid">
            <label>ราคา (บาท)<input type="number" min={0} step="1" inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
            <label>รอบ (วัน)<input type="number" min={1} max={366} value={days} onChange={(e) => setDays(e.target.value)} /></label>
            <label>PC<input type="number" min={0} value={pcs} onChange={(e) => setPcs(e.target.value)} /></label>
            <label>โทรศัพท์<input type="number" min={0} value={phones} onChange={(e) => setPhones(e.target.value)} /></label>
            <label>คลิป/รอบ<input type="number" min={0} value={clips} disabled={unlimited} onChange={(e) => setClips(e.target.value)} /></label>
            <label className="check"><input type="checkbox" checked={unlimited} onChange={(e) => setUnlimited(e.target.checked)} /> ไม่จำกัดคลิป</label>
          </div>
          <div className="admin-plan-actions">
            <input aria-label={`เหตุผล: ${plan.code}`} placeholder="เหตุผล (อย่างน้อย 10 ตัวอักษร จะถูกบันทึก)" value={reason}
              onChange={(e) => setReason(e.target.value)} />
            <button type="button" className="btn btn-primary btn-small" disabled={busy || !reasonOk} onClick={saveVersion}>บันทึกราคา/สิทธิ์ (เวอร์ชันใหม่)</button>
            {!trial && (
              <button type="button" className="btn btn-secondary btn-small" disabled={busy || !reasonOk}
                onClick={() => void call(`/v1/admin/plans/${plan.code}/status`, { selling: !plan.is_purchasable },
                  `${plan.code}: ${plan.is_purchasable ? 'ปิดขายแล้ว' : 'เปิดขายแล้ว'}`)}>
                {plan.is_purchasable ? 'ปิดขาย' : 'เปิดขาย (Go live)'}
              </button>
            )}
            <button type="button" className="btn btn-secondary btn-small" disabled={busy || !reasonOk}
              onClick={() => void call(`/v1/admin/plans/${plan.code}/status`, { demo: !plan.example },
                `${plan.code}: ${plan.example ? 'เอาป้าย Demo ออกแล้ว' : 'ติดป้าย Demo แล้ว'}`)}>
              {plan.example ? 'เอาป้าย Demo ออก' : 'ติดป้าย Demo'}
            </button>
          </div>
        </>
      )}
    </article>
  )
}

export function AdminPlans({ isAdmin }: { isAdmin: boolean }) {
  const [rows, setRows] = useState<AdminPlan[]>([])
  const [message, setMessage] = useState('')
  const load = useCallback(() => {
    api<{ items: AdminPlan[] }>('/v1/admin/plans').then((r) => setRows(r.items)).catch(() => undefined)
  }, [])
  useEffect(() => { load() }, [load])

  return (
    <section className="card" aria-labelledby="plans-admin-title">
      <h2 id="plans-admin-title">แพ็กเกจและราคา</h2>
      <p className="muted">
        เปลี่ยนราคา/สิทธิ์ = สร้างเวอร์ชันใหม่ ลูกค้าที่จ่ายแล้วใช้เวอร์ชันเดิมจนต่ออายุ • เปิด/ปิดขายและป้าย Demo มีผลทันที
        • การรับเงินจริงยังปิด (sandbox) จนกว่าจะเลือกผู้ให้บริการชำระเงิน
      </p>
      {message && <Alert kind="success">{message}</Alert>}
      <div className="admin-plans">
        {latestByCode(rows).map((p) => (
          <PlanEditor key={`${p.code}-${p.version}-${p.is_purchasable}-${p.example}`} plan={p} isAdmin={isAdmin}
            onDone={(m) => { setMessage(m); load() }} />
        ))}
      </div>
      <details>
        <summary>ทุกเวอร์ชัน</summary>
        <table className="table">
          <thead><tr><th>แพ็กเกจ</th><th>ราคา</th><th>วัน</th><th>PC / โทรศัพท์</th><th>คลิป/รอบ</th><th>ขาย</th><th>Demo</th></tr></thead>
          <tbody>{rows.map((p) => (
            <tr key={`${p.code}-${p.version}`}><td>{p.code} v{p.version}<div className="hint">{p.name}</div></td>
              <td>{baht(p.price_satang)}</td><td>{p.interval_days}</td><td>{p.max_registered_agents} / {p.max_devices}</td>
              <td>{clipsLabel(p.clips_per_month)}</td><td>{p.is_purchasable ? 'ใช่' : '—'}</td><td>{p.example ? 'ใช่' : '—'}</td></tr>
          ))}</tbody>
        </table>
      </details>
    </section>
  )
}
