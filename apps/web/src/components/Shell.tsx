import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'

const NAV = [
  { to: '/', label: 'แดชบอร์ด', end: true },
  { to: '/create', label: 'สร้างงาน' },
  { to: '/jobs', label: 'งานผลิตคลิป' },
  { to: '/environments', label: 'Environments' },
  { to: '/agent-tokens', label: 'Agent Token' },
  { to: '/agents', label: 'Agent' },
  { to: '/devices', label: 'โทรศัพท์' },
]

export function Shell({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  const navigate = useNavigate()

  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="auth-brand"><span className="brand-mark" aria-hidden="true">p</span> punpun</div>
        <nav aria-label="เมนูหลัก" className="nav">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <header className="topbar">
          <h1>{title}</h1>
          <div className="topbar-actions">
            {actions}
            <button type="button" className="btn btn-secondary" onClick={signOut}>ออกจากระบบ</button>
          </div>
        </header>
        {children}
      </main>
    </div>
  )
}
