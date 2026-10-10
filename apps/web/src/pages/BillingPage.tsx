import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'
import { baht, clipsLabel, quotaText, type Plan, type Quota } from '../lib/plans'

/* P6 (sandbox, E-45): plans, current cycle, checkout and history. Rights change only when the
   server has a verified payment event; returning from the payment page grants nothing by itself. */

type Subscription = {
  status: 'trial' | 'active' | 'expired'; plan: Plan; cycle_start: string; cycle_end: string
  paid_cycles_ahead: number; next_plan: Plan | null
  quota: Quota
}
type Payment = {
  id: string; plan: { code: string; name: string }; amount_satang: number; currency: string
  status: 'pending' | 'succeeded' | 'failed' | 'refunded'; applied: string | null; created_at: string
}

const STATUS: Record<Subscription['status'], { text: string; badge: string }> = {
  trial: { text: 'ทดลองใช้', badge: 'warn' },
  active: { text: 'ใช้งานอยู่', badge: 'online' },
  expired: { text: 'หมดอายุ', badge: 'revoked' },
}
const PAY: Record<Payment['status'], { text: string; badge: string }> = {
  pending: { text: 'รอผลการชำระ', badge: 'stale' },
  succeeded: { text: 'ชำระแล้ว', badge: 'online' },
  failed: { text: 'ไม่สำเร็จ', badge: 'revoked' },
  refunded: { text: 'คืนเงินแล้ว', badge: 'expired' },
}


export function BillingPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [plans, setPlans] = useState<Plan[]>([])
  const [note, setNote] = useState('')
  const [sub, setSub] = useState<Subscription | null>(null)
  const [history, setHistory] = useState<Payment[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const watching = params.get('payment')

  const load = useCallback(async () => {
    try {
      const [p, s, h] = await Promise.all([
        api<{ items: Plan[]; note: string }>('/v1/billing/plans'),
        api<Subscription>('/v1/billing/subscription'),
        api<{ items: Payment[] }>('/v1/billing/payments'),
      ])
      setPlans(p.items)
      setNote(p.note)
      setSub(s)
      setHistory(h.items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])

  const watched = history.find((h) => h.id === watching)
  useEffect(() => {
    void load()
    if (!watching) return
    const timer = window.setInterval(() => void load(), 3000)  // the result comes from the provider event
    return () => window.clearInterval(timer)
  }, [load, watching])

  async function buy(code: string) {
    setBusy(code)
    setError('')
    try {
      const pay = await api<Payment & { checkout_url: string }>('/v1/billing/checkout', {
        method: 'POST', body: { plan_code: code, idempotency_key: crypto.randomUUID().replace(/-/g, '') },
      })
      navigate(pay.checkout_url)
    } catch (err) {
      const ae = err as ApiError
      setError(ae.code === 'CHANGE_PENDING' ? 'มีการเปลี่ยนแพ็กเกจรอรอบถัดไปอยู่แล้ว' : ae.message)
      setBusy('')
    }
  }

  return (
    <Shell title="แพ็กเกจและการชำระเงิน">
      {error && <Alert kind="error">{error}</Alert>}
      <Alert kind="info">{note || 'ระบบชำระเงินยังเป็น sandbox'} — ยังไม่มีการเก็บเงินจริง</Alert>
      {watched && watched.status === 'pending' && <Alert kind="info">กำลังรอผลการชำระเงินจากผู้ให้บริการ…</Alert>}
      {watched && watched.status === 'succeeded' && <Alert kind="success">ชำระเงินสำเร็จ ({watched.plan.name})</Alert>}
      {watched && watched.status === 'failed' && <Alert kind="error">ชำระเงินไม่สำเร็จ ไม่มีการเปลี่ยนแพ็กเกจ</Alert>}

      {sub && (
        <section className="card" aria-labelledby="sub-title" data-testid="subscription">
          <div className="card-head">
            <h2 id="sub-title">{sub.plan.name}</h2>
            <span className={`badge badge-${STATUS[sub.status].badge}`}>{STATUS[sub.status].text}</span>
          </div>
          <dl className="facts">
            <dt>รอบนี้</dt><dd>{formatDate(sub.cycle_start)} – {formatDate(sub.cycle_end)}</dd>
            <dt>โควตาคลิป</dt><dd data-testid="quota">{quotaText(sub.quota)}</dd>
            <dt>PC / โทรศัพท์</dt>
            <dd>{sub.plan.limits.registered_agents} เครื่อง / {sub.plan.limits.devices} เครื่อง</dd>
            {sub.paid_cycles_ahead > 0 && (
              <><dt>ต่ออายุแล้ว</dt><dd>อีก {sub.paid_cycles_ahead} รอบ{sub.next_plan ? ` • รอบถัดไปเปลี่ยนเป็น ${sub.next_plan.name}` : ''}</dd></>
            )}
          </dl>
          {sub.status === 'expired' && <Alert kind="error">แพ็กเกจหมดอายุ: สร้างงานใหม่ไม่ได้ และโพสต์ที่ตั้งเวลาไว้จะรอจนกว่าจะต่ออายุ</Alert>}
        </section>
      )}

      <section className="card" aria-labelledby="plans-title">
        <h2 id="plans-title">เลือกแพ็กเกจ</h2>
        <p className="muted"><strong>ไม่คืนเงินทุกกรณี</strong> • ชำระครั้งละ 1 รอบ ({plans[0]?.interval_days ?? 30} วัน) ถ้ายังมีรอบที่ใช้อยู่ รอบที่ซื้อจะเริ่มต่อจากรอบปัจจุบัน และเปลี่ยนแพ็กเกจได้ตอนเริ่มรอบถัดไป</p>
        <div className="plan-grid">
          {plans.map((p) => (
            <div key={p.code} className="plan" data-testid={`plan-${p.code}`}>
              <h3>{p.name}</h3>
              <div className="plan-price">{baht(p.price_satang)}<span className="muted"> / {p.interval_days} วัน</span></div>
              <ul className="plan-limits">
                <li>{clipsLabel(p.limits.clips_per_cycle)} ต่อรอบ</li>
                <li>โทรศัพท์ {p.limits.devices} เครื่อง • PC {p.limits.registered_agents} เครื่อง</li>
              </ul>
              <button type="button" className="btn btn-primary" onClick={() => buy(p.code)} disabled={busy !== ''} aria-busy={busy === p.code}>
                {busy === p.code ? 'กำลังสร้างรายการ…' : sub?.status === 'active' ? 'ต่ออายุ/ซื้อรอบถัดไป' : 'ซื้อแพ็กเกจนี้'}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="history-title">
        <h2 id="history-title">ประวัติการชำระเงิน</h2>
        {history.length === 0 && <p className="muted">ยังไม่มีรายการ</p>}
        {history.length > 0 && (
          <table className="table">
            <thead><tr><th>วันที่</th><th>แพ็กเกจ</th><th>จำนวน</th><th>สถานะ</th></tr></thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} data-testid="payment-row">
                  <td>{formatDate(h.created_at)}</td>
                  <td>{h.plan.name}</td>
                  <td>{baht(h.amount_satang)}</td>
                  <td><span className={`badge badge-${PAY[h.status].badge}`}>{PAY[h.status].text}</span>
                    {h.status === 'pending' && <> <Link to={`/billing/sandbox/${h.id}`}>ไปหน้าชำระ</Link></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Shell>
  )
}

/** The sandbox provider's own page (stands in for the real provider's hosted checkout, D06). */
export function SandboxPayPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [pay, setPay] = useState<Payment | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<Payment>(`/v1/billing/payments/${id}`).then(setPay).catch((err) => setError((err as ApiError).message))
  }, [id])

  const done = useMemo(() => pay && pay.status !== 'pending', [pay])

  async function send(outcome: 'succeeded' | 'failed' | 'pending') {
    setBusy(true)
    try {
      await api(`/v1/billing/sandbox/${id}/simulate`, { method: 'POST', body: { outcome } })
      navigate(`/billing?payment=${id}`)  // back to the shop: it shows what the server recorded
    } catch (err) {
      setError((err as ApiError).message)
      setBusy(false)
    }
  }

  return (
    <Shell title="ชำระเงิน (Sandbox)">
      <Alert kind="info">หน้านี้จำลองผู้ให้บริการรับชำระเงินเพื่อทดสอบเท่านั้น ไม่มีการตัดเงินจริง</Alert>
      {error && <Alert kind="error">{error}</Alert>}
      {pay && (
        <section className="card" aria-labelledby="pay-title">
          <h2 id="pay-title">{pay.plan.name}</h2>
          <p className="plan-price" data-testid="pay-amount">{baht(pay.amount_satang)}</p>
          <p className="hint">การชำระนี้ไม่คืนเงินทุกกรณี</p>
          {done ? <p className="muted">รายการนี้มีผลแล้ว: {PAY[pay.status].text}</p> : (
            <div className="row-actions">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => send('succeeded')}>จำลอง: ชำระสำเร็จ</button>
              <button type="button" className="btn btn-danger-outline" disabled={busy} onClick={() => send('failed')}>จำลอง: ชำระไม่สำเร็จ</button>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => send('pending')}>จำลอง: ยังรอผล</button>
            </div>
          )}
        </section>
      )}
    </Shell>
  )
}
