/** PO 2026-10-10: link a PC to an Environment with a short code typed into the Agent's settings
 * window, instead of copying a long Agent token. The code lasts 10 minutes and works once. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { Environment } from '../lib/types'
import { Alert } from './ui'

type Code = { code: string; expires_at: string; expires_in_s: number; environment: { id: string; name: string } }

function left(expiresAt: string, now: number): string {
  const s = Math.max(0, Math.round((new Date(expiresAt).getTime() - now) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function PairingCode() {
  const [envs, setEnvs] = useState<Environment[] | null>(null)
  const [envId, setEnvId] = useState('')
  const [code, setCode] = useState<Code | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    api<{ items: Environment[] }>('/v1/environments')
      .then(({ items }) => { setEnvs(items); setEnvId(items[0]?.id ?? '') })
      .catch((err: ApiError) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!code) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [code])

  async function create() {
    setBusy(true)
    setError('')
    try {
      setCode(await api<Code>('/v1/agent-pairing-codes', { method: 'POST', body: { environment_id: envId } }))
      setNow(Date.now())
    } catch (err) {
      setError((err as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  const expired = code !== null && new Date(code.expires_at).getTime() <= now

  if (envs?.length === 0) {
    return <p className="muted">ต้องมี Environment ก่อน — <Link to="/environments">สร้าง Environment</Link></p>
  }
  return (
    <div className="pairing" data-testid="pairing">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="pairing-row">
        {envs && envs.length > 1 && (
          <div className="field">
            <label htmlFor="pair-env">เชื่อมกับ Environment</label>
            <select id="pair-env" value={envId} onChange={(e) => { setEnvId(e.target.value); setCode(null) }}>
              {envs.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </div>
        )}
        <button type="button" className="btn btn-primary" disabled={busy || !envId} onClick={create}>
          {code ? 'สร้างรหัสใหม่' : 'สร้างรหัสเชื่อมต่อ'}
        </button>
      </div>
      {code && !expired && (
        <p className="pairing-code" aria-live="polite">
          <code data-testid="pairing-code">{code.code}</code>
          <span className="muted">ใส่ในหน้าต่าง "ตั้งค่า punpun Agent" ภายใน {left(code.expires_at, now)} นาที
            • ใช้ได้ครั้งเดียว • Environment {code.environment.name}</span>
        </p>
      )}
      {expired && <p className="muted" role="status">รหัสหมดอายุแล้ว — สร้างรหัสใหม่</p>}
    </div>
  )
}
