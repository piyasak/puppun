import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Alert, AuthCard, Field, Submit } from '../components/ui'
import { ApiError, api, type Me } from '../lib/api'
import { supabase } from '../lib/supabase'

/** Loads /v1/me; sends users who have not finished onboarding to /onboarding. */
function useMe() {
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  useEffect(() => {
    let alive = true
    api<Me>('/v1/me')
      .then((m) => alive && setMe(m))
      .catch((e: ApiError) => alive && setError(e))
    return () => {
      alive = false
    }
  }, [])
  return { me, error }
}

export function OnboardingPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [accept, setAccept] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!accept) {
      setError('กรุณายอมรับคำรับรองสิทธิ์ในเนื้อหา')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api('/v1/onboarding', {
        method: 'POST',
        body: { username, workspace_name: workspace || null, accept_rights: true },
      })
      navigate('/', { replace: true })
    } catch (err) {
      const e = err as ApiError
      if (e.code === 'ALREADY_ONBOARDED') navigate('/', { replace: true })
      else if (e.code === 'VALIDATION_ERROR') setError('ชื่อผู้ใช้ใช้ได้เฉพาะ a-z, 0-9, _ . - ยาว 3–32 ตัว')
      else setError(e.message)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="ตั้งค่าบัญชี" subtitle="ขั้นตอนเดียวก่อนเริ่มใช้งาน">
      <form onSubmit={submit} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="ชื่อผู้ใช้" autoComplete="username" required value={username}
          hint="ใช้คู่กับ Agent Token บนเครื่อง Windows • a-z, 0-9, _ . - ยาว 3–32 ตัว"
          onChange={(e) => setUsername(e.target.value)} />
        <Field label="ชื่อ Workspace (ไม่บังคับ)" value={workspace} onChange={(e) => setWorkspace(e.target.value)} />
        <div className="check">
          <input id="accept-rights" type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
          <label htmlFor="accept-rights">
            ข้าพเจ้ารับรองว่ามีสิทธิ์ใช้และเผยแพร่เนื้อหาที่นำเข้าระบบ (ลิงก์และไฟล์ต้นฉบับ) และรับผิดชอบต่อการโพสต์ของบัญชีนี้
          </label>
        </div>
        <Submit busy={busy}>เริ่มใช้งาน</Submit>
      </form>
    </AuthCard>
  )
}

export function HomePage() {
  const { me, error } = useMe()
  const navigate = useNavigate()

  if (error?.code === 'ONBOARDING_REQUIRED') return <Navigate to="/onboarding" replace />

  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="เมนูหลัก">
        <div className="auth-brand"><span className="brand-mark">p</span> punpun</div>
        <nav>
          <a className="nav-item active" href="/" aria-current="page">แดชบอร์ด</a>
        </nav>
      </aside>
      <main className="content">
        <header className="topbar">
          <h1>แดชบอร์ด</h1>
          <button type="button" className="btn btn-secondary" onClick={signOut}>ออกจากระบบ</button>
        </header>
        {error && <Alert kind="error">{error.message}</Alert>}
        {!me && !error && <p className="muted" role="status">กำลังโหลด…</p>}
        {me && (
          <section className="card" aria-labelledby="ws-title">
            <h2 id="ws-title">{me.workspace.name}</h2>
            <dl className="facts">
              <dt>ผู้ใช้</dt><dd data-testid="me-username">{me.user.username}</dd>
              <dt>อีเมล</dt><dd data-testid="me-email">{me.user.email}</dd>
              <dt>บทบาท</dt><dd>{me.role === 'owner' ? 'เจ้าของ' : me.role}</dd>
              <dt>เขตเวลา</dt><dd>{me.workspace.timezone}</dd>
              <dt>คำรับรองสิทธิ์</dt>
              <dd>{me.rights_declaration ? `ยอมรับแล้ว (ฉบับ ${me.rights_declaration.version})` : 'ยังไม่ยอมรับ'}</dd>
            </dl>
          </section>
        )}
      </main>
    </div>
  )
}
