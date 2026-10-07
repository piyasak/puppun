import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { HomePage, OnboardingPage } from './pages/AppPages'
import { ForgotPage, LoginPage, ResetPage, SignupPage } from './pages/AuthPages'
import { EnvironmentsPage } from './pages/EnvironmentsPage'
import { TokensPage } from './pages/TokensPage'
import { AgentsPage } from './pages/AgentsPage'
import { DevicesPage } from './pages/DevicesPage'

function RequireSession({ children }: { children: ReactNode }) {
  const { session, ready } = useAuth()
  if (!ready) return <p className="muted center" role="status">กำลังโหลด…</p>
  return session ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot" element={<ForgotPage />} />
          <Route path="/reset" element={<ResetPage />} />
          <Route path="/onboarding" element={<RequireSession><OnboardingPage /></RequireSession>} />
          <Route path="/" element={<RequireSession><HomePage /></RequireSession>} />
          <Route path="/environments" element={<RequireSession><EnvironmentsPage /></RequireSession>} />
          <Route path="/agent-tokens" element={<RequireSession><TokensPage /></RequireSession>} />
          <Route path="/agents" element={<RequireSession><AgentsPage /></RequireSession>} />
          <Route path="/devices" element={<RequireSession><DevicesPage /></RequireSession>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
