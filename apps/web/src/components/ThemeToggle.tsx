import { useState } from 'react'

const KEY = 'punpun-theme'

/** Dark is the default theme; this switches to light and remembers it in this browser only. */
export function ThemeToggle() {
  const [light, setLight] = useState(() => document.documentElement.dataset.theme === 'light')

  function toggle() {
    const next = !light
    setLight(next)
    if (next) document.documentElement.dataset.theme = 'light'
    else delete document.documentElement.dataset.theme
    try {
      localStorage.setItem(KEY, next ? 'light' : 'dark')
    } catch {
      // Private windows may refuse storage; the switch still works for this visit.
    }
  }

  return (
    <button type="button" className="icon-btn" aria-pressed={light} aria-label="ธีมสว่าง" title={light ? 'เปลี่ยนเป็นธีมมืด' : 'เปลี่ยนเป็นธีมสว่าง'}
      onClick={toggle}>
      {light ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  )
}
