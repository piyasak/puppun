import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { OnboardingPage } from './pages/AppPages'
import { HomePage } from './pages/DashboardPage'
import { ConfirmPage, ForgotPage, LoginPage, ResetPage, SignupPage } from './pages/AuthPages'
import { EnvironmentsPage } from './pages/EnvironmentsPage'
import { TokensPage } from './pages/TokensPage'
import { AgentsPage } from './pages/AgentsPage'
import { DevicesPage } from './pages/DevicesPage'
import { CreateJobPage } from './pages/CreateJobPage'
import { JobsPage } from './pages/JobsPage'
import { JobDetailPage } from './pages/JobDetailPage'
import { SchedulePage } from './pages/SchedulePage'
import { BillingPage, SandboxPayPage } from './pages/BillingPage'
import { AdminPage } from './pages/AdminPage'
import { LandingPage } from './pages/LandingPage'

function RequireSession({ children }: { children: ReactNode }) {
  const { session, ready } = useAuth()
  if (!ready) return <p className="muted center" role="status">กำลังโหลด…</p>
  return session ? children : <Navigate to="/login" replace />
}

/** `/` is the marketing page for visitors and the dashboard once signed in. */
function HomeOrLanding() {
  const { session, ready } = useAuth()
  if (!ready) return <p className="muted center" role="status">กำลังโหลด…</p>
  return session ? <HomePage /> : <LandingPage />
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
          <Route path="/auth/confirm" element={<ConfirmPage />} />
          <Route path="/onboarding" element={<RequireSession><OnboardingPage /></RequireSession>} />
          <Route path="/" element={<HomeOrLanding />} />
          <Route path="/environments" element={<RequireSession><EnvironmentsPage /></RequireSession>} />
          <Route path="/agent-tokens" element={<RequireSession><TokensPage /></RequireSession>} />
          <Route path="/agents" element={<RequireSession><AgentsPage /></RequireSession>} />
          <Route path="/devices" element={<RequireSession><DevicesPage /></RequireSession>} />
          <Route path="/create" element={<RequireSession><CreateJobPage /></RequireSession>} />
          <Route path="/jobs" element={<RequireSession><JobsPage /></RequireSession>} />
          <Route path="/jobs/:id" element={<RequireSession><JobDetailPage /></RequireSession>} />
          <Route path="/schedule" element={<RequireSession><SchedulePage /></RequireSession>} />
          <Route path="/billing" element={<RequireSession><BillingPage /></RequireSession>} />
          <Route path="/billing/sandbox/:id" element={<RequireSession><SandboxPayPage /></RequireSession>} />
          <Route path="/admin" element={<RequireSession><AdminPage /></RequireSession>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
