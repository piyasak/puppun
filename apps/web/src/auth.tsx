import type { Session } from '@supabase/supabase-js'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { supabase } from './lib/supabase'

type AuthState = { session: Session | null; ready: boolean }

const AuthContext = createContext<AuthState>({ session: null, ready: false })

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ session: null, ready: false })

  useEffect(() => {
    // INITIAL_SESSION arrives after supabase-js has read any confirmation/reset link in the URL.
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setState({ session, ready: true })
    })
    return () => data.subscription.unsubscribe()
  }, [])

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  return useContext(AuthContext)
}
