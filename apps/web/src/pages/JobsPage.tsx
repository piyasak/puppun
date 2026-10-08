import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { IN_PROGRESS, STATE, sourceLabel, type Job, type JobState } from '../lib/jobs'
import { formatDate } from '../lib/types'

const TABS: { id: string; text: string; states: JobState[] | null }[] = [
  { id: 'all', text: 'ทั้งหมด', states: null },
  { id: 'running', text: 'กำลังผลิต', states: IN_PROGRESS },
  { id: 'review', text: 'รอตรวจ', states: ['READY_FOR_REVIEW'] },
  { id: 'action', text: 'ต้องดำเนินการ', states: ['NEEDS_ACTION'] },
  { id: 'failed', text: 'ล้มเหลว/ยกเลิก', states: ['FAILED', 'CANCELLED'] },
]

export function JobsPage() {
  const [items, setItems] = useState<Job[] | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('all')

  const load = useCallback(async () => {
    try {
      setItems((await api<{ items: Job[] }>('/v1/jobs')).items)
      setError('')
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])

  const running = items?.some((j) => IN_PROGRESS.includes(j.state)) ?? false
  useEffect(() => {
    void load()
    // Refresh while something is being made; the Agent reports each step to the server.
    const timer = window.setInterval(() => void load(), running ? 5_000 : 30_000)
    return () => window.clearInterval(timer)
  }, [load, running])

  const current = TABS.find((t) => t.id === tab) ?? TABS[0]
  const shown = items?.filter((j) => !current.states || current.states.includes(j.state))

  return (
    <Shell title="งานผลิตคลิป" actions={<Link className="btn btn-primary" to="/create">สร้างงาน</Link>}>
      {error && <Alert kind="error">{error}</Alert>}
      <section className="card">
        <div className="tabs" role="tablist" aria-label="กรองตามสถานะ">
          {TABS.map((t) => {
            const count = items?.filter((j) => !t.states || t.states.includes(j.state)).length
            return (
              <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
                className={`tab${tab === t.id ? ' active' : ''}`} onClick={() => setTab(t.id)}>
                {t.text}{count !== undefined && <span className="tab-count">{count}</span>}
              </button>
            )
          })}
        </div>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {shown?.length === 0 && (
          <p className="muted">
            {items?.length === 0 ? <>ยังไม่มีงาน — <Link to="/create">สร้างงานแรก</Link></> : 'ไม่มีงานในสถานะนี้'}
          </p>
        )}
        <ul className="rows">
          {shown?.map((j) => {
            const s = STATE[j.state]
            return (
              <li key={j.id} className="row" data-testid="job-row">
                <div className="row-main">
                  <Link to={`/jobs/${j.id}`} className="row-title">{sourceLabel(j)}</Link>
                  <span className={`badge badge-${s.badge}`}>{s.text}</span>
                  <span className="muted">
                    {j.planned_clips ?? j.requested_clips} คลิป • {j.review_mode === 'review' ? 'ตรวจเอง' : 'อนุมัติอัตโนมัติ'} • สร้าง {formatDate(j.created_at)}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      </section>
    </Shell>
  )
}
