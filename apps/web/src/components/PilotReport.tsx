import { useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { Alert } from './ui'

/* G7-01 / G7-02: what the pilot looks like from the server's records. Counts only, nothing dropped. */

type Report = {
  onboarding: {
    new_workspaces: number; started: number; started_pct: number | null; started_within_minutes: number
    median_minutes_to_first_job: number | null; target: string
    workspaces: { workspace_id: string; name: string; signed_up_at: string; minutes_to_agent: number | null
      minutes_to_phone: number | null; minutes_to_job: number | null; started_in_time: boolean }[]
  }
  jobs: { succeeded: number; failed: number; cancelled: number; in_progress: number; success_pct: number | null; target: string }
  posts: { verified: number; unknown: number; failed: number; dry_runs: number; in_progress: number
    success_pct: number | null; target: string }
}

const pct = (v: number | null) => (v === null ? '—' : `${v}%`)
const mins = (v: number | null) => (v === null ? '—' : `${v} นาที`)

export function PilotReport() {
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Report>(`/v1/admin/pilot-report?days=${days}`)
      .then((r) => { setReport(r); setError('') })
      .catch((err) => setError((err as ApiError).message))
  }, [days])

  return (
    <section className="card" aria-labelledby="pilot-title" data-testid="pilot-report">
      <div className="card-head">
        <h2 id="pilot-title">รายงาน Pilot (G7)</h2>
        <label>ช่วง{' '}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>{d} วันล่าสุด</option>)}
          </select>
        </label>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {report && (
        <>
          <dl className="facts">
            <dt>ผู้ใช้ใหม่</dt>
            <dd>{report.onboarding.new_workspaces} คน • เริ่มใช้งานใน {report.onboarding.started_within_minutes} นาที {report.onboarding.started} คน ({pct(report.onboarding.started_pct)}) • ค่ากลางถึงงานแรก {mins(report.onboarding.median_minutes_to_first_job)}</dd>
            <dt>งานผลิตคลิป</dt>
            <dd>สำเร็จ {report.jobs.succeeded} • ไม่สำเร็จ {report.jobs.failed} ({pct(report.jobs.success_pct)} สำเร็จ) • ยกเลิก {report.jobs.cancelled} • กำลังทำ {report.jobs.in_progress}</dd>
            <dt>โพสต์จริง</dt>
            <dd>ยืนยันแล้ว {report.posts.verified} • Unknown {report.posts.unknown} • ไม่สำเร็จ {report.posts.failed} ({pct(report.posts.success_pct)} สำเร็จ) • รอ/กำลังโพสต์ {report.posts.in_progress}</dd>
            <dt>Dry run</dt><dd>{report.posts.dry_runs} (ไม่นับเป็นโพสต์)</dd>
          </dl>
          <p className="hint">{report.onboarding.target} • {report.jobs.target} • {report.posts.target}</p>
          {report.onboarding.workspaces.length > 0 && (
            <table className="table">
              <thead><tr><th>Workspace</th><th>ถึง Agent</th><th>ถึงโทรศัพท์</th><th>ถึงงานแรก</th><th>ทันเวลา</th></tr></thead>
              <tbody>
                {report.onboarding.workspaces.map((w) => (
                  <tr key={w.workspace_id}>
                    <td>{w.name}</td><td>{mins(w.minutes_to_agent)}</td><td>{mins(w.minutes_to_phone)}</td>
                    <td>{mins(w.minutes_to_job)}</td><td>{w.started_in_time ? 'ใช่' : 'ไม่'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}
