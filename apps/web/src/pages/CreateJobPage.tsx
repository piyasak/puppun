import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shell } from '../components/Shell'
import { Alert, Field } from '../components/ui'
import { ApiError, api } from '../lib/api'
import type { Job } from '../lib/jobs'
import type { Environment, Usage } from '../lib/types'

/* /create (ui-map): 1 ต้นฉบับ → 2 รูปแบบ → 3 ตรวจและสร้าง. Device/time selection arrives with P4. */

const LENGTHS = [
  { id: '180-300', min: 180, max: 300, text: '3–5 นาที (แนะนำ)' },
  { id: '60-180', min: 60, max: 180, text: '1–3 นาที' },
  { id: '30-60', min: 30, max: 60, text: '30–60 วินาที' },
]
const STEP_TITLES = ['ต้นฉบับ', 'รูปแบบ', 'ตรวจและสร้าง']

function createError(e: ApiError): string {
  if (e.code === 'UNSUPPORTED_URL') return 'ลิงก์นี้ใช้ไม่ได้ รองรับเฉพาะลิงก์ https ของ YouTube และ Bilibili'
  if (e.code === 'UNSUPPORTED_FILE') return e.message
  if (e.code === 'QUOTA_EXHAUSTED') return 'โควตาคลิปของเดือนนี้หมดแล้ว'
  if (e.code === 'RIGHTS_REQUIRED') return 'ต้องยอมรับคำรับรองสิทธิ์ในเนื้อหาก่อน'
  return e.message
}

export function CreateJobPage() {
  const navigate = useNavigate()
  const [envs, setEnvs] = useState<Environment[] | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [step, setStep] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // One key per form: a double click or a retry after a network error never makes two jobs.
  const idempotencyKey = useMemo(() => crypto.randomUUID().replace(/-/g, ''), [])

  const [envId, setEnvId] = useState('')
  const [kind, setKind] = useState<'url' | 'local_file'>('url')
  const [url, setUrl] = useState('')
  const [fileName, setFileName] = useState('')
  const [clips, setClips] = useState(3)
  const [length, setLength] = useState(LENGTHS[0].id)
  const [subtitles, setSubtitles] = useState(true)
  const [mode, setMode] = useState<'review' | 'auto'>('review')
  const [confirmAuto, setConfirmAuto] = useState(false)

  useEffect(() => {
    Promise.all([api<{ items: Environment[] }>('/v1/environments'), api<Usage>('/v1/workspace/usage')])
      .then(([list, u]) => {
        setEnvs(list.items)
        setUsage(u)
        if (list.items.length > 0) setEnvId((cur) => cur || list.items[0].id)
      })
      .catch((err) => setError((err as ApiError).message))
  }, [])

  const len = LENGTHS.find((l) => l.id === length) ?? LENGTHS[0]
  const env = envs?.find((e) => e.id === envId)
  const available = usage?.clips.available ?? 0

  function stepError(n: number): string {
    if (n === 0) {
      if (!envId) return 'เลือก Environment ของเครื่องที่จะผลิตคลิป'
      if (kind === 'url' && !/^https:\/\/\S+$/.test(url.trim())) return 'ใส่ลิงก์ YouTube หรือ Bilibili ที่ขึ้นต้นด้วย https://'
      if (kind === 'local_file' && !fileName.trim()) return 'ใส่ชื่อไฟล์วิดีโอ'
      if (kind === 'local_file' && /[\\/:]/.test(fileName)) return 'ใส่เฉพาะชื่อไฟล์ ไม่ต้องใส่โฟลเดอร์'
    }
    if (n === 1) {
      if (!Number.isInteger(clips) || clips < 1 || clips > 20) return 'จำนวนคลิปต้องอยู่ระหว่าง 1–20'
      if (mode === 'auto' && !confirmAuto) return 'ยืนยันการอนุมัติอัตโนมัติก่อน'
    }
    return ''
  }

  function next(e: FormEvent) {
    e.preventDefault()
    const problem = stepError(step)
    setError(problem)
    if (!problem) setStep(step + 1)
  }

  async function create() {
    setBusy(true)
    setError('')
    try {
      const job = await api<Job>('/v1/jobs', {
        method: 'POST',
        body: {
          idempotency_key: idempotencyKey, environment_id: envId,
          source: kind === 'url' ? { kind, url: url.trim() } : { kind, file_name: fileName.trim() },
          requested_clips: clips, clip_min_s: len.min, clip_max_s: len.max, subtitles,
          review_mode: mode, confirm_auto: mode === 'auto' && confirmAuto,
        },
      })
      navigate(`/jobs/${job.id}`)
    } catch (err) {
      setError(createError(err as ApiError))
      setBusy(false)
    }
  }

  return (
    <Shell title="สร้างงานผลิตคลิป">
      <ol className="stepper" aria-label="ขั้นตอน">
        {STEP_TITLES.map((t, i) => (
          <li key={t} className={i === step ? 'current' : i < step ? 'done' : ''} aria-current={i === step ? 'step' : undefined}>
            <span className="step-no">{i + 1}</span> {t}
          </li>
        ))}
      </ol>
      {error && <Alert kind="error">{error}</Alert>}
      {envs?.length === 0 && (
        <Alert kind="info">ยังไม่มี Environment — สร้าง Environment และติดตั้ง Agent ก่อน แล้วกลับมาสร้างงาน</Alert>
      )}

      <section className="card" aria-labelledby="step-title">
        <h2 id="step-title">{step + 1}. {STEP_TITLES[step]}</h2>

        {step === 0 && (
          <form onSubmit={next} noValidate>
            <div className="field">
              <label htmlFor="env">Environment (เครื่องที่ผลิตคลิป)</label>
              <select id="env" value={envId} onChange={(e) => setEnvId(e.target.value)}>
                {envs?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
              <p className="hint">Agent ใน Environment นี้จะดาวน์โหลด ตัดและสร้างคลิปบนเครื่อง Windows ของคุณ</p>
            </div>
            <fieldset className="choices">
              <legend>แหล่งที่มา</legend>
              <label className="check"><input type="radio" name="kind" checked={kind === 'url'} onChange={() => setKind('url')} />
                <span>ลิงก์ YouTube หรือ Bilibili</span></label>
              <label className="check"><input type="radio" name="kind" checked={kind === 'local_file'} onChange={() => setKind('local_file')} />
                <span>ไฟล์วิดีโอบนเครื่อง Agent<br /><span className="hint">ไฟล์ไม่ถูกอัปโหลดขึ้นเว็บ Agent อ่านจากโฟลเดอร์วิดีโอบนเครื่องโดยตรง</span></span></label>
            </fieldset>
            {kind === 'url'
              ? <Field label="ลิงก์ต้นฉบับ" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=…" hint="ใช้เฉพาะเนื้อหาที่คุณมีสิทธิ์ตามที่ยอมรับไว้ตอนสมัคร" />
              : <Field label="ชื่อไฟล์วิดีโอ" value={fileName} onChange={(e) => setFileName(e.target.value)}
                  placeholder="ตอนที่1.mp4" hint="ชื่อไฟล์ในโฟลเดอร์วิดีโอของ Agent (ตัวเลือก --media-dir) รองรับ .mp4 .mkv .mov .webm .m4v .avi" />}
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={!envs?.length}>ถัดไป</button>
            </div>
          </form>
        )}

        {step === 1 && (
          <form onSubmit={next} noValidate>
            <div className="grid-3">
              <Field label="จำนวนคลิป" type="number" min={1} max={20} inputMode="numeric" value={String(clips)}
                onChange={(e) => setClips(Math.trunc(Number(e.target.value)) || 0)} hint="ถ้าต้นฉบับสั้น ระบบจะตัดได้น้อยลงและแจ้งให้ทราบ" />
              <div className="field">
                <label htmlFor="length">ความยาวต่อคลิป</label>
                <select id="length" value={length} onChange={(e) => setLength(e.target.value)}>
                  {LENGTHS.map((l) => <option key={l.id} value={l.id}>{l.text}</option>)}
                </select>
              </div>
            </div>
            <label className="check"><input type="checkbox" checked={subtitles} onChange={(e) => setSubtitles(e.target.checked)} />
              <span>ใส่ซับจากต้นฉบับลงในคลิป<br /><span className="hint">ปิดถ้าต้นฉบับมีซับฝังในภาพอยู่แล้ว ไม่งั้นซับจะซ้อนกัน</span></span></label>
            <fieldset className="choices">
              <legend>การตรวจก่อนเผยแพร่</legend>
              <label className="check"><input type="radio" name="mode" checked={mode === 'review'} onChange={() => setMode('review')} />
                <span>ตรวจเองทุกคลิป (แนะนำ)<br /><span className="hint">คลิปจะไม่ถูกโพสต์จนกว่าคุณจะกดอนุมัติ</span></span></label>
              <label className="check"><input type="radio" name="mode" checked={mode === 'auto'} onChange={() => setMode('auto')} />
                <span>อนุมัติอัตโนมัติ<br /><span className="hint">อนุมัติเฉพาะคลิปที่ผ่านการตรวจไฟล์ทุกข้อ (ขนาด เสียง ความยาว) — ไม่ได้ตรวจเนื้อหาให้</span></span></label>
              {mode === 'auto' && (
                <label className="check"><input type="checkbox" checked={confirmAuto} onChange={(e) => setConfirmAuto(e.target.checked)} />
                  <span>ฉันเข้าใจว่าคลิปจะถูกอนุมัติโดยไม่มีคนดูก่อน</span></label>
              )}
            </fieldset>
            <div className="form-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setStep(0)}>ย้อนกลับ</button>
              <button type="submit" className="btn btn-primary">ถัดไป</button>
            </div>
          </form>
        )}

        {step === 2 && (
          <div>
            <dl className="facts">
              <dt>Environment</dt><dd>{env?.name}</dd>
              <dt>ต้นฉบับ</dt><dd>{kind === 'url' ? url.trim() : `ไฟล์บนเครื่อง: ${fileName.trim()}`}</dd>
              <dt>คลิป</dt><dd>{clips} คลิป ยาว {len.text.replace(' (แนะนำ)', '')}</dd>
              <dt>ซับ</dt><dd>{subtitles ? 'ใส่ซับจากต้นฉบับ' : 'ไม่ใส่ซับ'}</dd>
              <dt>การตรวจ</dt><dd>{mode === 'review' ? 'ตรวจเองทุกคลิป' : 'อนุมัติอัตโนมัติเมื่อผ่านการตรวจไฟล์'}</dd>
              <dt>โควตา</dt>
              <dd data-testid="quota-preview">ใช้สูงสุด {clips} คลิป จากที่เหลือ {available} คลิปเดือนนี้ — หักเฉพาะคลิปที่ส่งถึงจริง</dd>
            </dl>
            {available < clips && available > 0 && (
              <Alert kind="info">โควตาเหลือน้อยกว่าจำนวนที่ขอ ถ้าต้นฉบับตัดได้มากกว่า {available} คลิป งานจะหยุดรอให้ดำเนินการ</Alert>
            )}
            {available <= 0 && <Alert kind="error">โควตาคลิปของเดือนนี้หมดแล้ว</Alert>}
            <div className="form-actions">
              <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>ย้อนกลับ</button>
              <button type="button" className="btn btn-primary" onClick={create} disabled={busy || available <= 0} aria-busy={busy}>
                {busy ? 'กำลังสร้าง…' : 'สร้างงาน'}
              </button>
            </div>
          </div>
        )}
      </section>
    </Shell>
  )
}
