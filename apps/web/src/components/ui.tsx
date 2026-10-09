import { useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { ThemeToggle } from './ThemeToggle'

export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <main className="auth-page">
      <div className="auth-top"><ThemeToggle /></div>
      <div className="auth-brand" aria-hidden="true">
        <span className="brand-mark">p</span> punpun
      </div>
      <section className="card auth-card" aria-labelledby="auth-title">
        <h1 id="auth-title">{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
        {children}
      </section>
    </main>
  )
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }

export function Field({ label, hint, error, ...input }: FieldProps) {
  const id = useId()
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
      {hint && <p id={`${id}-hint`} className="hint">{hint}</p>}
      {error && <p id={`${id}-error`} className="field-error">{error}</p>}
    </div>
  )
}

export function Alert({ kind, children }: { kind: 'error' | 'success' | 'info'; children: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

export function Submit({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button type="submit" className="btn btn-primary btn-block" disabled={busy} aria-busy={busy}>
      {busy ? 'กำลังดำเนินการ…' : children}
    </button>
  )
}
