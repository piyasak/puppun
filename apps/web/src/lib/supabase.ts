import { createClient } from '@supabase/supabase-js'

// Public values only: project URL and the publishable key. Never put a service-role key here.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

if (!url || !key) {
  throw new Error('VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY must be set (apps/web/.env.local)')
}

export const supabase = createClient(url, key, {
  auth: {
    // Implicit flow: the confirmation/reset link works even when opened in a different
    // browser from the one that requested it (PKCE needs the same browser).
    flowType: 'implicit',
    detectSessionInUrl: true,
    persistSession: true,
    autoRefreshToken: true,
  },
})
