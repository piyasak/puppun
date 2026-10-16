import { useEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api, type Me } from '../lib/api'
import { supabase } from '../lib/supabase'
import { ThemeToggle } from './ThemeToggle'

const NAV = [
  { to: '/', label: 'แดชบอร์ด', end: true },
  { to: '/create', label: 'สร้างงาน' },
  { to: '/jobs', label: 'งานผลิตคลิป' },
  { to: '/schedule', label: 'ตารางโพสต์' },
  { to: '/environments', label: 'Environments' },
  { to: '/agent-tokens', label: 'Agent Token' },
  { to: '/agents', label: 'Agent' },
  { to: '/devices', label: 'โทรศัพท์' },
  { to: '/notifications', label: 'การแจ้งเตือน' },
  { to: '/billing', label: 'แพ็กเกจ' },
]

/** Cursor spotlight on cards (E-47 step 4): the card under the pointer gets its position for the CSS light. */
function spotlight(e: React.PointerEvent<HTMLElement>) {
  if (e.pointerType !== 'mouse') return
  const card = (e.target as HTMLElement).closest<HTMLElement>('.card')
  if (!card) return
  const r = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${e.clientX - r.left}px`)
  card.style.setProperty('--my', `${e.clientY - r.top}px`)
}

export function Shell({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [staff, setStaff] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    // The admin link shows only for platform staff; the API itself refuses everyone else.
    api<Me>('/v1/me').then((me) => setStaff(Boolean(me.user.platform_role))).catch(() => setStaff(false))
  }, [])

  // Phones: the menu closes on navigation and on Esc (focus goes back to the menu button).
  const [openedOn, setOpenedOn] = useState(pathname)
  if (menuOpen && openedOn !== pathname) setMenuOpen(false)
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMenuOpen(false)
        toggleRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  async function signOut() {
    await supabase.auth.signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-head">
          <div className="auth-brand"><span className="brand-mark" aria-hidden="true">p</span> punpun</div>
          <button ref={toggleRef} type="button" className="icon-btn menu-toggle" aria-expanded={menuOpen} aria-controls="main-menu"
            aria-label="เมนู" onClick={() => { setOpenedOn(pathname); setMenuOpen((o) => !o) }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              {menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        <div id="main-menu" className={`sidebar-body${menuOpen ? ' open' : ''}`}>
          <nav aria-label="เมนูหลัก" className="nav">
            {[...NAV, ...(staff ? [{ to: '/admin', label: 'ผู้ดูแลระบบ', end: false }] : [])].map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}
                className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <span className="hint">ธีม</span>
            <ThemeToggle />
          </div>
        </div>
      </aside>
      <main className="content" onPointerMove={spotlight}>
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
