import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Shell } from '../components/Shell'
import { AdminPlans } from '../components/AdminPlans'
import { PilotReport } from '../components/PilotReport'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'
import { quotaText, type Quota } from '../lib/plans'

/* P6.4 (E-46): platform staff. Support reads; admin changes, always with a reason that goes to
   the audit trail together with the values before and after. Customers never see this page
   (the API answers 404 to them). */

type WorkspaceRow = {
  id: string; name: string; account_check: boolean; owner: { username: string; email: string } | null
  subscription: { status: string; plan: string; cycle_end: string; paid_cycles_ahead: number }
}
type WorkspaceDetail = WorkspaceRow & {
  quota: Quota
  counts: { jobs: number; devices: number }
  payments: { id: string; status: string; amount_satang?: number; created_at: string }[]
  audit: { action: string; at: string; reason: string | null; details: Record<string, unknown> | null }[]
}
type JobRow = { id: string; workspace_id: string; state: string; source: string; error_code: string | null; created_at: string }
type PlanRow = { code: string }
type GrantRow = {
  id: string; account: string; visibility: string; max_posts: number; used_posts: number; remaining: number
  expires_at: string; reason: string; status: 'active' | 'expired' | 'used_up' | 'revoked'
}
const GRANT_STATUS: Record<GrantRow['status'], string> = { active: 'ใช้ได้', expired: 'หมดอายุ', used_up: 'ใช้ครบแล้ว', revoked: 'ยกเลิกแล้ว' }

function ReasonForm({ label, children, onSubmit }: {
  label: string
  children?: React.ReactNode
  onSubmit: (reason: string) => Promise<void>
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await onSubmit(reason)
      setReason('')
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="admin-action" onSubmit={submit}>
      {children}
      <input aria-label={`เหตุผล: ${label}`} placeholder="เหตุผล (อย่างน้อย 10 ตัวอักษร จะถูกบันทึก)" value={reason}
        onChange={(e) => setReason(e.target.value)} />
      <button type="submit" className="btn btn-secondary btn-small" disabled={busy || reason.trim().length < 10}>{label}</button>
    </form>
  )
}

export function AdminPage() {
  const [role, setRole] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<WorkspaceRow[]>([])
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null)
  const [jobs, setJobs] = useState<JobRow[]>([])
  const [jobId, setJobId] = useState('')
  const [plans, setPlans] = useState<PlanRow[]>([])
  const [error, setError] = useState('')
  const [days, setDays] = useState(30)
  const [units, setUnits] = useState(10)
  const [planCode, setPlanCode] = useState('pro')
  const [when, setWhen] = useState<'now' | 'next_cycle'>('next_cycle')
  const [grants, setGrants] = useState<GrantRow[]>([])
  const [grantAccount, setGrantAccount] = useState('')
  const [grantPosts, setGrantPosts] = useState(10)
  const [grantDays, setGrantDays] = useState(14)

  useEffect(() => {
    api<{ role: string }>('/v1/admin/me').then((r) => setRole(r.role)).catch(() => setRole(''))
    api<{ items: PlanRow[] }>('/v1/admin/plans').then((r) => setPlans(r.items)).catch(() => undefined)
  }, [])

  const search = useCallback(async (e?: FormEvent) => {
    e?.preventDefault()
    try {
      setRows((await api<{ items: WorkspaceRow[] }>(`/v1/admin/workspaces?q=${encodeURIComponent(q)}`)).items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [q])

  async function open(id: string) {
    setDetail(await api<WorkspaceDetail>(`/v1/admin/workspaces/${id}`))
    setGrants((await api<{ items: GrantRow[] }>(`/v1/admin/workspaces/${id}/posting-grants`)).items)
  }

  /** Q-42: real posting for one TikTok account of this Workspace ("only you"), audited with a reason. */
  async function grantAct(path: string, body: Record<string, unknown>) {
    if (!detail) return
    setError('')
    try {
      await api(path, { method: 'POST', body })
      await open(detail.id)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function act(path: string, body: Record<string, unknown>) {
    if (!detail) return
    setError('')
    try {
      const out = await api<WorkspaceDetail | { quota: unknown }>(`/v1/admin/workspaces/${detail.id}/${path}`, { method: 'POST', body })
      if ('audit' in out) setDetail(out)
      else await open(detail.id)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  /** Start a customer's job again (missing clip files, new video location), with a reason. */
  async function resetJob(jobId: string, reason: string) {
    setError('')
    try {
      const out = await api<{ id: string; state: string; reset: string }>(`/v1/admin/jobs/${jobId}/reset`, { method: 'POST', body: { reason } })
      setJobs((rows) => rows.map((r) => (r.id === out.id ? { ...r, state: out.state, error_code: null } : r)))
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  async function findJobs(e: FormEvent) {
    e.preventDefault()
    try {
      const qs = jobId.trim() ? `job_id=${encodeURIComponent(jobId.trim())}` : 'state=FAILED'
      setJobs((await api<{ items: JobRow[] }>(`/v1/admin/jobs?${qs}`)).items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  if (role === '') return <Shell title="ไม่พบหน้านี้"><p className="muted">ไม่พบหน้านี้</p></Shell>
  const isAdmin = role === 'admin'

  return (
    <Shell title="ผู้ดูแลระบบ">
      {role && <Alert kind="info">สิทธิ์: {isAdmin ? 'Admin (แก้ไขได้ ทุกการแก้ไขต้องมีเหตุผลและถูกบันทึก)' : 'Support (ดูอย่างเดียว)'}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}

      <section className="card" aria-labelledby="ws-title">
        <h2 id="ws-title">Workspace / ผู้ใช้</h2>
        <form className="admin-search" onSubmit={search}>
          <input aria-label="ค้นหา" placeholder="อีเมล, username หรือชื่อ Workspace" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit" className="btn btn-primary btn-small">ค้นหา</button>
        </form>
        <table className="table">
          <thead><tr><th>Workspace</th><th>เจ้าของ</th><th>แพ็กเกจ</th><th>สถานะ</th><th /></tr></thead>
          <tbody>
            {rows.map((w) => (
              <tr key={w.id} data-testid="admin-ws">
                <td>{w.name}</td>
                <td>{w.owner?.username}<div className="hint">{w.owner?.email}</div></td>
                <td>{w.subscription.plan}</td>
                <td>{w.subscription.status} • ถึง {formatDate(w.subscription.cycle_end)}</td>
                <td><button type="button" className="btn btn-secondary btn-small" onClick={() => open(w.id)}>เปิด</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {detail && (
        <section className="card" aria-labelledby="detail-title" data-testid="admin-detail">
          <h2 id="detail-title">{detail.name}</h2>
          <dl className="facts">
            <dt>แพ็กเกจ</dt><dd>{detail.subscription.plan} • {detail.subscription.status} • ถึง {formatDate(detail.subscription.cycle_end)}</dd>
            <dt>โควตา</dt><dd data-testid="admin-quota">{quotaText(detail.quota)}</dd>
            <dt>งาน / โทรศัพท์</dt><dd>{detail.counts.jobs} / {detail.counts.devices}</dd>
          </dl>
          {isAdmin && (
            <div className="admin-actions">
              <ReasonForm label="ขยายรอบ" onSubmit={(reason) => act('extend', { days, reason })}>
                <input type="number" aria-label="จำนวนวัน" min={1} max={366} value={days} onChange={(e) => setDays(Number(e.target.value))} />
              </ReasonForm>
              <ReasonForm label="ปรับโควตา" onSubmit={(reason) => act('quota', { units, reason, idempotency_key: crypto.randomUUID().replace(/-/g, '') })}>
                <input type="number" aria-label="จำนวนคลิป (+ คืน / − หัก)" value={units} onChange={(e) => setUnits(Number(e.target.value))} />
              </ReasonForm>
              <ReasonForm label="เปลี่ยนแพ็กเกจ" onSubmit={(reason) => act('plan', { plan_code: planCode, when, reason })}>
                <select aria-label="แพ็กเกจ" value={planCode} onChange={(e) => setPlanCode(e.target.value)}>
                  {[...new Set(plans.map((p) => p.code))].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <select aria-label="มีผลเมื่อ" value={when} onChange={(e) => setWhen(e.target.value as 'now' | 'next_cycle')}>
                  <option value="next_cycle">รอบถัดไป</option><option value="now">ทันที</option>
                </select>
              </ReasonForm>
              <ReasonForm label="สิ้นสุดแพ็กเกจทันที" onSubmit={(reason) => act('end', { reason })} />
            </div>
          )}
          <h3>ตรวจบัญชี TikTok</h3>
          <p className="muted" data-testid="admin-account-check">
            {detail.account_check
              ? 'เปิดอยู่: Agent ตรวจว่าโทรศัพท์ล็อกอินบัญชีที่ตั้งไว้ก่อนโพสต์จริง และผูกผลโพสต์กับบัญชีนั้น'
              : 'ปิดอยู่: Agent โพสต์ลงบัญชีที่ล็อกอินในโทรศัพท์โดยไม่ตรวจ สิทธิ์โพสต์จริงของ Workspace นี้ใช้ได้กับทุกบัญชี ยืนยันผลด้วยรหัสท้ายข้อความเท่านั้น (ต้องใช้ Agent 0.5.7 ขึ้นไป)'}
          </p>
          {isAdmin && (
            <ReasonForm label={detail.account_check ? 'ปิดการตรวจบัญชี' : 'เปิดการตรวจบัญชี'}
              onSubmit={(reason) => act('account-check', { enabled: !detail.account_check, reason })} />
          )}
          <h3>สิทธิ์โพสต์จริง</h3>
          <p className="muted">ไม่มีสิทธิ์ = ทุกโพสต์หยุดก่อนกดโพสต์ (dry run) • ตอนนี้เปิดได้เฉพาะแบบ "เฉพาะฉัน" • ต้องใช้ Agent 0.4.0 ขึ้นไป</p>
          <ul className="rows" data-testid="admin-grants">{grants.map((g) => (
            <li key={g.id} className="row"><div className="row-main">
              <strong>{g.account === '*' ? 'ทุกบัญชี' : `@${g.account}`} • {GRANT_STATUS[g.status]}</strong>
              <span className="muted">ใช้ {g.used_posts}/{g.max_posts} • ถึง {formatDate(g.expires_at)} • {g.reason}</span>
            </div>
            {isAdmin && g.status === 'active' && (
              <ReasonForm label="ยกเลิกสิทธิ์" onSubmit={(reason) => grantAct(`/v1/admin/posting-grants/${g.id}/revoke`, { reason })} />
            )}</li>
          ))}</ul>
          {grants.length === 0 && <p className="muted">ยังไม่มีสิทธิ์โพสต์จริง</p>}
          {isAdmin && (
            <ReasonForm label="ให้สิทธิ์โพสต์จริง" onSubmit={(reason) => grantAct(`/v1/admin/workspaces/${detail.id}/posting-grants`,
              { account: grantAccount, max_posts: grantPosts, days: grantDays, visibility: 'only_me', reason })}>
              <input aria-label="บัญชี TikTok" placeholder={detail.account_check ? '@บัญชี' : '@บัญชี (เว้นว่าง = ทุกบัญชี)'} value={grantAccount} onChange={(e) => setGrantAccount(e.target.value)} />
              <input type="number" aria-label="จำนวนโพสต์สูงสุด" min={1} max={1000} value={grantPosts} onChange={(e) => setGrantPosts(Number(e.target.value))} />
              <input type="number" aria-label="ใช้ได้กี่วัน" min={1} max={90} value={grantDays} onChange={(e) => setGrantDays(Number(e.target.value))} />
            </ReasonForm>
          )}
          <h3>การชำระเงิน</h3>
          <ul className="rows">{detail.payments.map((p) => (
            <li key={p.id} className="row"><span>{formatDate(p.created_at)} • {p.status}{p.amount_satang !== undefined ? ` • ฿${p.amount_satang / 100}` : ''}</span></li>
          ))}</ul>
          <h3>Audit</h3>
          <ul className="rows" data-testid="admin-audit">{detail.audit.map((a, i) => (
            <li key={i} className="row"><div className="row-main"><strong>{a.action}</strong>
              <span className="muted">{formatDate(a.at)}{a.reason ? ` • ${a.reason}` : ''}</span></div></li>
          ))}</ul>
        </section>
      )}

      <section className="card" aria-labelledby="jobs-title">
        <h2 id="jobs-title">ค้นหางาน (Support อ้างอิง Job ID)</h2>
        <form className="admin-search" onSubmit={findJobs}>
          <input aria-label="Job ID" placeholder="Job ID (เว้นว่าง = งานที่ล้มเหลวล่าสุด)" value={jobId} onChange={(e) => setJobId(e.target.value)} />
          <button type="submit" className="btn btn-primary btn-small">ค้นหา</button>
        </form>
        <table className="table">
          <thead><tr><th>Job</th><th>สถานะ</th><th>ต้นฉบับ</th><th>ข้อผิดพลาด</th>{isAdmin && <th>เริ่มงานใหม่</th>}</tr></thead>
          <tbody>{jobs.map((j) => (
            <tr key={j.id} data-testid="admin-job"><td><code>{j.id.slice(0, 8)}</code><div className="hint">{formatDate(j.created_at)}</div></td>
              <td>{j.state}</td><td>{j.source}</td><td>{j.error_code ?? '—'}</td>
              {isAdmin && (
                <td><ReasonForm label="เริ่มงานใหม่" onSubmit={(reason) => resetJob(j.id, reason)} /></td>
              )}</tr>
          ))}</tbody>
        </table>
      </section>

      <PilotReport />
      <AdminPlans isAdmin={role === 'admin'} />
    </Shell>
  )
}
