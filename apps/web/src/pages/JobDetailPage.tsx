import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import {
  CHECK_LABELS, FINISHED, IN_PROGRESS, STATE, STEPS, errorText, mmss, sourceLabel,
  type Clip, type JobDetail,
} from '../lib/jobs'
import { formatDate } from '../lib/types'
import { SchedulePanel } from './SchedulePanel'

function Timeline({ job }: { job: JobDetail }) {
  const reached = STEPS.findIndex((s) => s.state === job.state)
  const failedAt = FINISHED.includes(job.state) && job.state !== 'READY_FOR_REVIEW'
  return (
    <ol className="timeline" aria-label="ความคืบหน้า">
      {STEPS.map((s, i) => {
        const done = job.state === 'READY_FOR_REVIEW' || (reached >= 0 && i < reached)
        const current = !failedAt && i === reached && job.state !== 'READY_FOR_REVIEW'
        return (
          <li key={s.state} className={done ? 'done' : current ? 'current' : ''} aria-current={current ? 'step' : undefined}>
            {s.text}
          </li>
        )
      })}
    </ol>
  )
}

/** Q-33: the video never leaves the Agent's PC; the page shows three frames and where the file is. */
function AgentStill({ clip }: { clip: Clip }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    let alive = true
    api<{ url: string }>(`/v1/clips/${clip.id}/media`)
      .then((m) => alive && setUrl(m.url))
      .catch((err: ApiError) => alive && setError(err.message))
    return () => { alive = false }
  }, [clip.id])

  async function copy() {
    try {
      await navigator.clipboard.writeText(clip.agent_path ?? '')
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <figure className="agent-still" data-testid="clip-still">
      {url
        ? <img src={url} alt={`ภาพจาก 3 ช่วงของคลิป ${clip.index}`} width={810} height={480} onError={() => setError('โหลดภาพไม่ได้')} />
        : <div className="agent-still-empty">{error || 'กำลังโหลดภาพ…'}</div>}
      <figcaption>
        {clip.agent_file_deleted_at
          ? <span className="hint" data-testid="agent-file-deleted">ลบไฟล์วิดีโอจากเครื่อง Agent แล้วหลังโพสต์สำเร็จ ({formatDate(clip.agent_file_deleted_at)})</span>
          : <span className="hint">วิดีโอเก็บไว้บนเครื่อง Agent (ไม่ได้อัปโหลด) — เปิดดูจากโฟลเดอร์นี้บนเครื่องนั้น</span>}
        {clip.agent_path && !clip.agent_file_deleted_at && (
          <span className="agent-path">
            <code data-testid="agent-path">{clip.agent_path}</code>
            <button type="button" className="btn btn-secondary btn-small" onClick={copy}>{copied ? 'คัดลอกแล้ว' : 'คัดลอก path'}</button>
          </span>
        )}
      </figcaption>
    </figure>
  )
}

function Preview({ clip }: { clip: Clip }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function open() {
    setBusy(true)
    setError('')
    try {
      // Short-lived signed link (5 min); asked for only when the owner wants to watch.
      setUrl((await api<{ url: string }>(`/v1/clips/${clip.id}/media`)).url)
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  if (!clip.uploaded) return <div className="preview preview-empty">รอไฟล์จาก Agent</div>
  if (clip.file_location === 'agent') return <AgentStill clip={clip} />
  return (
    <div className="preview">
      {url ? (
        <video src={url} controls preload="metadata" playsInline data-testid="clip-video"
          aria-label={`ตัวอย่างคลิป ${clip.index}`} onError={() => { setUrl(null); setError('ลิงก์ตัวอย่างหมดอายุ กดดูอีกครั้ง') }} />
      ) : (
        <button type="button" className="btn btn-secondary" onClick={open} disabled={busy} aria-busy={busy}>
          {busy ? 'กำลังเปิด…' : '▶ ดูตัวอย่าง'}
        </button>
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}

function MetadataEditor({ clip, onSaved }: { clip: Clip; onSaved: (c: Clip) => void }) {
  const [caption, setCaption] = useState(clip.metadata.caption ?? '')
  const [tags, setTags] = useState(clip.metadata.hashtags.join(' '))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const dirty = caption !== (clip.metadata.caption ?? '') || tags !== clip.metadata.hashtags.join(' ')

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const hashtags = tags.split(/[\s,]+/).filter(Boolean)
      onSaved(await api<Clip>(`/v1/clips/${clip.id}/metadata`, {
        method: 'PATCH', body: { expected_version: clip.metadata.version, caption, hashtags },
      }))
    } catch (err) {
      const ae = err as ApiError
      setError(ae.code === 'VERSION_CONFLICT' ? 'ข้อความถูกแก้จากที่อื่นแล้ว โหลดหน้าใหม่ก่อนแก้' : ae.message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} noValidate className="meta-form">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="field">
        <label htmlFor={`cap-${clip.id}`}>คำบรรยาย (Caption)</label>
        <textarea id={`cap-${clip.id}`} rows={3} maxLength={2200} value={caption} onChange={(e) => setCaption(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`tag-${clip.id}`}>แฮชแท็ก</label>
        <input id={`tag-${clip.id}`} value={tags} onChange={(e) => setTags(e.target.value)} aria-describedby={`tag-${clip.id}-hint`} />
        <p id={`tag-${clip.id}-hint`} className="hint">คั่นด้วยเว้นวรรค เช่น #คลิปสั้น #ตอนต่อไป</p>
      </div>
      <div className="form-actions">
        <span className="hint">ข้อความเวอร์ชัน {clip.metadata.version}{clip.approval.approved ? ' — แก้แล้วต้องอนุมัติใหม่' : ''}</span>
        <button type="submit" className="btn btn-secondary" disabled={busy || !dirty} aria-busy={busy}>
          {busy ? 'กำลังบันทึก…' : 'บันทึกข้อความ'}
        </button>
      </div>
    </form>
  )
}

function ClipCard({ clip, jobCancelled, onChange }: { clip: Clip; jobCancelled: boolean; onChange: (c: Clip) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const failedChecks = clip.checks?.checks.filter((c) => !c.ok) ?? []
  const lostApproval = !clip.approval.approved && clip.approval.metadata_version !== null

  async function act(path: 'approve' | 'unapprove') {
    setBusy(true)
    setError('')
    try {
      onChange(await api<Clip>(`/v1/clips/${clip.id}/${path}`, {
        method: 'POST', body: path === 'approve' ? { metadata_version: clip.metadata.version } : undefined,
      }))
    } catch (err) {
      const ae = err as ApiError
      setError(ae.code === 'VERSION_CONFLICT' ? 'ข้อความเปลี่ยนแล้ว ตรวจข้อความล่าสุดก่อนอนุมัติ' : ae.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="clip-card" data-testid="clip-card">
      <Preview clip={clip} />
      <div className="clip-body">
        <div className="card-head">
          <h3>คลิป {clip.index}</h3>
          {clip.approval.approved
            ? <span className="badge badge-online" data-testid="approval">อนุมัติแล้ว{clip.approval.mode === 'auto' ? ' (อัตโนมัติ)' : ''}</span>
            : <span className="badge badge-warn" data-testid="approval">ยังไม่อนุมัติ</span>}
          {clip.check_status === 'passed' && <span className="badge badge-active">ผ่านการตรวจไฟล์</span>}
          {clip.check_status === 'failed' && <span className="badge badge-revoked">ไม่ผ่านการตรวจไฟล์</span>}
          {clip.check_status === 'skipped' && <span className="badge badge-expired">ยังไม่ได้ตรวจไฟล์</span>}
        </div>
        <p className="muted">
          ช่วงต้นฉบับ {mmss(clip.start_ms)}–{mmss(clip.end_ms)} • ยาว {mmss(clip.duration_ms)} • {(clip.size_bytes / 1e6).toFixed(1)} MB
        </p>
        <p className="clip-title"><span className="muted">ชื่อในวิดีโอ:</span> {clip.title ?? '—'}
          <span className="hint"> (อยู่ในภาพ ถ้าจะเปลี่ยนต้องสร้างคลิปใหม่)</span></p>
        {failedChecks.length > 0 && (
          <Alert kind="error">
            ไม่ผ่าน: {failedChecks.map((c) => (c.name === 'readable'
              ? 'ไฟล์นี้ไม่ใช่วิดีโอที่เปิดได้'
              : `${CHECK_LABELS[c.name] ?? c.name} (${c.detail ?? '—'})`)).join(', ')}
          </Alert>
        )}
        {lostApproval && <Alert kind="info">ข้อความถูกแก้หลังอนุมัติ ต้องตรวจและอนุมัติใหม่</Alert>}
        <MetadataEditor key={`${clip.id}-${clip.metadata.version}`} clip={clip} onSaved={onChange} />
        {error && <Alert kind="error">{error}</Alert>}
        <div className="row-actions">
          {clip.approval.approved ? (
            <button type="button" className="btn btn-secondary" onClick={() => act('unapprove')} disabled={busy}>ยกเลิกการอนุมัติ</button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => act('approve')}
              disabled={busy || jobCancelled || !clip.uploaded || clip.check_status === 'failed'}>
              อนุมัติคลิปนี้ (ข้อความเวอร์ชัน {clip.metadata.version})
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

export function JobDetailPage() {
  const { id } = useParams()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [error, setError] = useState('')
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setJob(await api<JobDetail>(`/v1/jobs/${id}`))
      setError('')
    } catch (err) {
      const ae = err as ApiError
      setError(ae.status === 404 ? 'ไม่พบงานนี้' : ae.message)
    }
  }, [id])

  const running = job ? IN_PROGRESS.includes(job.state) : false
  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (!running) return  // poll only while the Agent is making clips
    const timer = window.setInterval(() => void load(), 5_000)
    return () => window.clearInterval(timer)
  }, [load, running])

  async function cancel() {
    setBusy(true)
    try {
      await api(`/v1/jobs/${id}/cancel`, { method: 'POST' })
      setConfirmCancel(false)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
      setConfirmCancel(false)
    } finally {
      setBusy(false)
    }
  }

  const replaceClip = (c: Clip) => setJob((j) => (j ? { ...j, clips: j.clips.map((x) => (x.id === c.id ? c : x)) } : j))
  const s = job ? STATE[job.state] : null

  return (
    <Shell title="รายละเอียดงาน" actions={<Link className="btn btn-secondary" to="/jobs">กลับไปรายการงาน</Link>}>
      {error && <Alert kind="error">{error}</Alert>}
      {!job && !error && <p className="muted" role="status">กำลังโหลด…</p>}
      {job && s && (
        <>
          <section className="card" aria-labelledby="job-title">
            <div className="card-head">
              <h2 id="job-title">{sourceLabel(job)}</h2>
              <span className={`badge badge-${s.badge}`} data-testid="job-state">{s.text}</span>
            </div>
            <Timeline job={job} />
            {job.error && (
              <Alert kind="error"><strong>{errorText(job.error.code)}</strong>{job.error.detail && <><br />{job.error.detail}</>}</Alert>
            )}
            {job.notice === 'INSUFFICIENT_SOURCE' && (
              <Alert kind="info">ต้นฉบับตัดได้ {job.planned_clips} คลิปจากที่ขอ {job.requested_clips} คลิป — หักโควตาเฉพาะที่ได้จริง</Alert>
            )}
            {job.notice === 'PARTIAL_RENDER' && (
              <Alert kind="info">สร้างได้ {job.clips.filter((c) => c.uploaded).length} จาก {job.planned_clips} คลิป ส่วนที่ไม่สำเร็จไม่ถูกหักโควตา</Alert>
            )}
            <dl className="facts">
              <dt>คลิป</dt><dd>{job.auto_clips
                ? `คำนวณจากต้นฉบับ • ${job.planned_clips == null ? 'รอ Agent วัดความยาว' : `ได้ ${job.planned_clips} คลิป`}`
                : `ขอ ${job.requested_clips} • วางแผน ${job.planned_clips ?? '—'}`} • ยาว {mmss(job.clip_min_s * 1000)}–{mmss(job.clip_max_s * 1000)} นาที</dd>
              <dt>ต้นฉบับ</dt><dd>{job.source_duration_s ? `ยาว ${mmss(job.source_duration_s * 1000)}` : 'ยังไม่ได้ตรวจ'}</dd>
              <dt>การตรวจ</dt><dd>{job.review_mode === 'review' ? 'ตรวจเองทุกคลิป' : 'อนุมัติอัตโนมัติเมื่อผ่านการตรวจไฟล์'} • ซับ{job.subtitles ? 'จากต้นฉบับ' : ': ไม่ใส่'}</dd>
              <dt>หลังโพสต์</dt><dd data-testid="job-after-post">{job.delete_after_post ? 'ลบไฟล์คลิปบนเครื่อง Agent ถาวรเมื่อโพสต์สำเร็จ' : 'เก็บไฟล์คลิปไว้'}</dd>
              <dt>โควตา</dt><dd data-testid="job-quota">จอง {job.quota.reserved} • ใช้ {job.quota.settled} • คืน {job.quota.released}</dd>
              <dt>Seed</dt><dd><code>{job.seed}</code> (ใช้เลือกช่วงซ้ำได้)</dd>
              <dt>สร้าง</dt><dd>{formatDate(job.created_at)}{job.finished_at && ` • จบ ${formatDate(job.finished_at)}`}</dd>
            </dl>
            {!FINISHED.includes(job.state) && (
              <div className="form-actions">
                <button type="button" className="btn btn-danger-outline" onClick={() => setConfirmCancel(true)}>ยกเลิกงาน</button>
              </div>
            )}
          </section>

          <section className="card" aria-labelledby="clips-title">
            <h2 id="clips-title">คลิป</h2>
            {job.clips.length === 0 && (
              <p className="muted">{running ? 'Agent กำลังผลิต คลิปจะขึ้นที่นี่ทีละคลิป' : 'ไม่มีคลิป'}</p>
            )}
            <ul className="clip-list">
              {job.clips.map((c) => (
                <ClipCard key={c.id} clip={c} jobCancelled={job.state === 'CANCELLED'} onChange={replaceClip} />
              ))}
            </ul>
          </section>

          {job.state === 'READY_FOR_REVIEW' && (
            <SchedulePanel job={job}
              refresh={job.clips.map((c) => `${c.metadata.version}:${c.approval.approved}`).join(',')} />
          )}
        </>
      )}
      <ConfirmDialog open={confirmCancel} busy={busy} danger title="ยกเลิกงานนี้?" confirmLabel="ยกเลิกงาน"
        onConfirm={cancel} onCancel={() => setConfirmCancel(false)}>
        <p>Agent จะหยุดผลิตคลิปที่เหลือ โควตาที่จองไว้แต่ยังไม่ได้ใช้จะคืนทั้งหมด คลิปที่ส่งถึงแล้วยังอยู่</p>
      </ConfirmDialog>
    </Shell>
  )
}
