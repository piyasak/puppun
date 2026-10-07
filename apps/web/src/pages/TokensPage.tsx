import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Shell } from '../components/Shell'
import { Alert, Field } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate, type AgentToken, type Environment, type NewAgentToken } from '../lib/types'

const STATUS_TEXT: Record<AgentToken['status'], string> = { active: 'ใช้งานได้', expired: 'หมดอายุ', revoked: 'ยกเลิกแล้ว' }

/** Shows a new token exactly once. It lives only in component state and is dropped on close. */
function SecretPanel({ token, onDone }: { token: NewAgentToken; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => inputRef.current?.focus(), [])

  async function copy() {
    try {
      await navigator.clipboard.writeText(token.token)
      setCopied(true)
    } catch {
      inputRef.current?.select()
    }
  }

  return (
    <section className="card secret-card" aria-labelledby="secret-title">
      <h2 id="secret-title">คัดลอก Token ตอนนี้ — จะแสดงเพียงครั้งเดียว</h2>
      <Alert kind="info">
        นำ Token นี้ไปใส่ในโปรแกรม Agent บนเครื่อง Windows ({token.environment.name}) พร้อมชื่อผู้ใช้ของคุณ
        เมื่อปิดกล่องนี้แล้วจะดู Token เต็มอีกไม่ได้ ถ้าทำหายให้สร้างใหม่หรือหมุนเวียน (Rotate)
      </Alert>
      <div className="secret-row">
        <label htmlFor="new-token" className="sr-only">Agent Token</label>
        <input id="new-token" ref={inputRef} className="secret-input" readOnly value={token.token}
          onFocus={(e) => e.currentTarget.select()} data-testid="new-token" />
        <button type="button" className="btn btn-primary" onClick={copy}>{copied ? 'คัดลอกแล้ว ✓' : 'คัดลอก'}</button>
      </div>
      <button type="button" className="btn btn-secondary" onClick={onDone}>ฉันเก็บ Token แล้ว</button>
    </section>
  )
}

export function TokensPage() {
  const [items, setItems] = useState<AgentToken[] | null>(null)
  const [envs, setEnvs] = useState<Environment[]>([])
  const [error, setError] = useState('')
  const [fresh, setFresh] = useState<NewAgentToken | null>(null)
  const [envId, setEnvId] = useState('')
  const [name, setName] = useState('')
  const [days, setDays] = useState(90)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<{ kind: 'revoke' | 'rotate'; token: AgentToken } | null>(null)

  const load = useCallback(async () => {
    try {
      const [t, e] = await Promise.all([
        api<{ items: AgentToken[] }>('/v1/agent-tokens'),
        api<{ items: Environment[] }>('/v1/environments'),
      ])
      setItems(t.items)
      setEnvs(e.items)
      setEnvId((cur) => cur || e.items[0]?.id || '')
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function create(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const t = await api<NewAgentToken>('/v1/agent-tokens', {
        method: 'POST', body: { environment_id: envId, name: name.trim(), expires_in_days: days },
      })
      setFresh(t)
      setName('')
      await load()
    } catch (err) {
      const ae = err as ApiError
      setError(ae.code === 'TOKEN_LIMIT' ? ae.message : ae.code === 'VALIDATION_ERROR' ? 'กรุณากรอกชื่อ Token' : ae.message)
    } finally {
      setBusy(false)
    }
  }

  async function runConfirm() {
    if (!confirm) return
    setBusy(true)
    try {
      if (confirm.kind === 'revoke') {
        await api(`/v1/agent-tokens/${confirm.token.id}/revoke`, { method: 'POST' })
      } else {
        setFresh(await api<NewAgentToken>(`/v1/agent-tokens/${confirm.token.id}/rotate`, { method: 'POST' }))
      }
      setConfirm(null)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
      setConfirm(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title="Agent Token">
      {error && <Alert kind="error">{error}</Alert>}
      {fresh && <SecretPanel token={fresh} onDone={() => setFresh(null)} />}

      <section className="card" aria-labelledby="new-token-title">
        <h2 id="new-token-title">สร้าง Token</h2>
        {envs.length === 0 ? (
          <p className="muted">ต้องมี Environment ก่อน — <Link to="/environments">สร้าง Environment</Link></p>
        ) : (
          <form onSubmit={create} noValidate>
            <div className="grid-3">
              <div className="field">
                <label htmlFor="token-env">Environment</label>
                <select id="token-env" value={envId} onChange={(e) => setEnvId(e.target.value)}>
                  {envs.map((env) => <option key={env.id} value={env.id}>{env.name}</option>)}
                </select>
              </div>
              <Field label="ชื่อ Token" required value={name} onChange={(e) => setName(e.target.value)} hint="เช่น PC หน้าร้าน" />
              <div className="field">
                <label htmlFor="token-days">อายุ</label>
                <select id="token-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                  {[30, 90, 180, 365].map((d) => <option key={d} value={d}>{d} วัน</option>)}
                </select>
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy || !name.trim() || !envId} aria-busy={busy}>
                {busy ? 'กำลังสร้าง…' : 'สร้าง Token'}
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="card" aria-labelledby="token-list-title">
        <h2 id="token-list-title">Token ทั้งหมด</h2>
        {items === null && <p className="muted" role="status">กำลังโหลด…</p>}
        {items?.length === 0 && <p className="muted">ยังไม่มี Token</p>}
        <ul className="rows">
          {items?.map((t) => (
            <li key={t.id} className="row" data-testid="token-row">
              <div className="row-main">
                <strong>{t.name}</strong>
                <span className={`badge badge-${t.status}`}>{STATUS_TEXT[t.status]}</span>
                <span className="muted">
                  <code>cfat_{t.prefix}_…</code> • {t.environment.name} • หมดอายุ {formatDate(t.expires_at)}
                  {t.revoked_at && ` • ยกเลิกเมื่อ ${formatDate(t.revoked_at)}`}
                </span>
              </div>
              {t.status === 'active' && (
                <div className="row-actions">
                  <button type="button" className="btn btn-secondary" onClick={() => setConfirm({ kind: 'rotate', token: t })}>
                    Rotate
                  </button>
                  <button type="button" className="btn btn-danger-outline" onClick={() => setConfirm({ kind: 'revoke', token: t })}>
                    ยกเลิก Token
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <ConfirmDialog open={confirm !== null} busy={busy} danger={confirm?.kind === 'revoke'}
        title={confirm?.kind === 'revoke' ? `ยกเลิก Token "${confirm?.token.name}"?` : `Rotate Token "${confirm?.token.name}"?`}
        confirmLabel={confirm?.kind === 'revoke' ? 'ยกเลิก Token' : 'Rotate'}
        onConfirm={runConfirm} onCancel={() => setConfirm(null)}>
        {confirm?.kind === 'revoke'
          ? <p>Agent ที่ใช้ Token นี้จะหยุดรับงานใหม่ทันที งานที่กดโพสต์ไปแล้วจะถูกตรวจผลต่อ ไม่โพสต์ซ้ำ การยกเลิกย้อนกลับไม่ได้</p>
          : <p>ระบบจะออก Token ใหม่ให้ Environment เดิม และยกเลิก Token เดิมทันที ต้องนำ Token ใหม่ไปใส่ใน Agent</p>}
      </ConfirmDialog>
    </Shell>
  )
}
