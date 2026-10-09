import { createClient } from '@supabase/supabase-js'

// Public values only: project URL and the publishable key. Never put a service-role key here.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
// 'same-origin': the API serves this app itself (staging image), so requests go to /v1/... on the same host.
const apiUrl = import.meta.env.VITE_API_URL as string | undefined
export const API_URL = apiUrl === 'same-origin' ? '' : apiUrl ?? 'http://127.0.0.1:8000'

/**
 * Missing config is reported on screen at runtime (main.tsx). Throwing here at module scope made
 * the bundler treat everything after it as dead code when building without env vars, so the
 * production bundle silently lost the app (found 2026-10-08).
 */
export const configError: string | null =
  !url || !key ? 'VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY must be set (apps/web/.env.local)' : null

export const supabase = createClient(url || 'http://config-missing.invalid', key || 'config-missing', {
  auth: {
    // Implicit flow: the confirmation/reset link works even when opened in a different
    // browser from the one that requested it (PKCE needs the same browser).
    flowType: 'implicit',
    detectSessionInUrl: true,
    persistSession: true,
    autoRefreshToken: true,
  },
})
