import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AuthCard, Field, Submit } from '../components/ui'
import { ApiError, api } from '../lib/api'

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
