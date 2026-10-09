import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Alert, AuthCard, Field, Submit } from '../components/ui'
import { authMessage } from '../lib/authErrors'
import { supabase } from '../lib/supabase'

const MIN_PASSWORD = 10

function passwordProblem(password: string, confirm: string): string | undefined {
  if (password.length < MIN_PASSWORD) return `รหัสผ่านต้องมีอย่างน้อย ${MIN_PASSWORD} ตัวอักษร`
  if (password !== confirm) return 'รหัสผ่านทั้งสองช่องไม่ตรงกัน'
  return undefined
}

export function SignupPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const problem = passwordProblem(password, confirm)
    setFieldError(problem)
    if (problem) return
    setBusy(true)
    setError('')
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/` },
    })
    setBusy(false)
    if (error) setError(authMessage(error))
    else setSent(true)
  }

  if (sent) {
    return (
      <AuthCard title="ตรวจสอบอีเมลของคุณ">
        <Alert kind="success">
          เราส่งลิงก์ยืนยันไปที่ <strong>{email}</strong> แล้ว กดลิงก์ในอีเมลเพื่อเปิดใช้งานบัญชี
        </Alert>
        <p className="muted">ไม่พบอีเมล? ตรวจโฟลเดอร์สแปม หรือรอสักครู่แล้วลองสมัครใหม่</p>
        <Link to="/login">กลับไปหน้าเข้าสู่ระบบ</Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="สมัครสมาชิก" subtitle="สร้างบัญชีเพื่อเริ่มตัดคลิปและตั้งเวลาโพสต์">
      <form onSubmit={submit} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="อีเมล" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="รหัสผ่าน" type="password" autoComplete="new-password" required hint={`อย่างน้อย ${MIN_PASSWORD} ตัวอักษร`}
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <Field label="ยืนยันรหัสผ่าน" type="password" autoComplete="new-password" required error={fieldError}
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <Submit busy={busy}>สมัครสมาชิก</Submit>
      </form>
      <p className="switch">มีบัญชีแล้ว? <Link to="/login">เข้าสู่ระบบ</Link></p>
    </AuthCard>
  )
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { session, ready } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const notice = new URLSearchParams(location.search).get('reset') === '1'

  if (ready && session) return <Navigate to="/" replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (error) setError(authMessage(error))
    else navigate('/', { replace: true })
  }

  return (
    <AuthCard title="เข้าสู่ระบบ">
      <form onSubmit={submit} noValidate>
        {notice && <Alert kind="success">ตั้งรหัสผ่านใหม่แล้ว กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่</Alert>}
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="อีเมล" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field label="รหัสผ่าน" type="password" autoComplete="current-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <Submit busy={busy}>เข้าสู่ระบบ</Submit>
      </form>
      <p className="switch"><Link to="/forgot">ลืมรหัสผ่าน?</Link></p>
      <p className="switch">ยังไม่มีบัญชี? <Link to="/signup">สมัครสมาชิก</Link></p>
    </AuthCard>
  )
}

export function ForgotPage() {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset` })
    setBusy(false)
    // Same answer whether or not the account exists (FR-01); only rate limits are shown.
    if (error && (error.code === 'over_email_send_rate_limit' || error.code === 'over_request_rate_limit')) {
      setError(authMessage(error))
    } else {
      setDone(true)
    }
  }

  return (
    <AuthCard title="ลืมรหัสผ่าน" subtitle="กรอกอีเมลที่ใช้สมัคร เราจะส่งลิงก์สำหรับตั้งรหัสผ่านใหม่">
      {done ? (
        <Alert kind="success">หากอีเมลนี้มีบัญชีอยู่ เราได้ส่งลิงก์ตั้งรหัสผ่านใหม่ไปแล้ว</Alert>
      ) : (
        <form onSubmit={submit} noValidate>
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="อีเมล" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Submit busy={busy}>ส่งลิงก์ตั้งรหัสผ่านใหม่</Submit>
        </form>
      )}
      <p className="switch"><Link to="/login">กลับไปหน้าเข้าสู่ระบบ</Link></p>
    </AuthCard>
  )
}

const CONFIRM_TYPES = {
  email: { title: 'ยืนยันอีเมล', button: 'ยืนยันอีเมล', next: '/' },
  recovery: { title: 'ตั้งรหัสผ่านใหม่', button: 'ตั้งรหัสผ่านใหม่', next: '/reset' },
} as const

/**
 * E-28: email links land here instead of on Supabase's verify URL. The token is used only when the
 * person presses the button, so a mail scanner that opens (GETs) the link cannot use it up.
 */
export function ConfirmPage() {
  const navigate = useNavigate()
  const params = new URLSearchParams(useLocation().search)
  const tokenHash = params.get('token_hash') ?? ''
  const type = params.get('type') ?? ''
  const kind = type in CONFIRM_TYPES ? CONFIRM_TYPES[type as keyof typeof CONFIRM_TYPES] : undefined
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  if (!kind || !tokenHash || failed) {
    return (
      <AuthCard title="ลิงก์ไม่ถูกต้องหรือหมดอายุ">
        <Alert kind="error">ลิงก์นี้ใช้ไม่ได้แล้ว (ใช้ไปแล้วหรือหมดอายุ) กรุณาขอลิงก์ใหม่</Alert>
        <Link to={type === 'recovery' ? '/forgot' : '/login'}>{type === 'recovery' ? 'ขอลิงก์ใหม่' : 'ไปหน้าเข้าสู่ระบบ'}</Link>
      </AuthCard>
    )
  }

  async function confirm() {
    setBusy(true)
    const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type: type as 'email' | 'recovery' })
    if (error) {
      setBusy(false)
      setFailed(true)
      return
    }
    navigate(kind!.next, { replace: true })
  }

  return (
    <AuthCard title={kind.title} subtitle="กดปุ่มด้านล่างเพื่อดำเนินการต่อ">
      <button type="button" className="btn btn-primary btn-block" disabled={busy} aria-busy={busy} onClick={confirm}>
        {busy ? 'กำลังดำเนินการ…' : kind.button}
      </button>
    </AuthCard>
  )
}

export function ResetPage() {
  const navigate = useNavigate()
  const { session, ready } = useAuth()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [fieldError, setFieldError] = useState<string>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!ready) return null
  if (!session) {
    return (
      <AuthCard title="ลิงก์ไม่ถูกต้องหรือหมดอายุ">
        <Alert kind="error">ลิงก์ตั้งรหัสผ่านนี้ใช้ไม่ได้แล้ว กรุณาขอลิงก์ใหม่</Alert>
        <Link to="/forgot">ขอลิงก์ใหม่</Link>
      </AuthCard>
    )
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const problem = passwordProblem(password, confirm)
    setFieldError(problem)
    if (problem) return
    setBusy(true)
    setError('')
    const { error } = await supabase.auth.updateUser({ password })
    if (error) {
      setBusy(false)
      setError(authMessage(error))
      return
    }
    await supabase.auth.signOut()
    navigate('/login?reset=1', { replace: true })
  }

  return (
    <AuthCard title="ตั้งรหัสผ่านใหม่">
      <form onSubmit={submit} noValidate>
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="รหัสผ่านใหม่" type="password" autoComplete="new-password" required hint={`อย่างน้อย ${MIN_PASSWORD} ตัวอักษร`}
          value={password} onChange={(e) => setPassword(e.target.value)} />
        <Field label="ยืนยันรหัสผ่านใหม่" type="password" autoComplete="new-password" required error={fieldError}
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <Submit busy={busy}>บันทึกรหัสผ่านใหม่</Submit>
      </form>
    </AuthCard>
  )
}
