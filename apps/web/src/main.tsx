import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { configError } from './lib/supabase'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {configError ? (
      <main className="auth-page">
        <section className="card auth-card" role="alert">
          <h1>ตั้งค่าระบบไม่ครบ</h1>
          <p className="muted">{configError}</p>
        </section>
      </main>
    ) : (
      <App />
    )}
  </StrictMode>,
)
