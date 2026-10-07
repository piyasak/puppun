import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// Supabase settings are inlined at build time. A build without them would only contain the
// "config missing" screen, so refuse to build instead of shipping an empty app.
const REQUIRED = ['VITE_SUPABASE_URL', 'VITE_SUPABASE_PUBLISHABLE_KEY', 'VITE_API_URL']

export default defineConfig(({ command, mode }) => {
  if (command === 'build') {
    const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
    const missing = REQUIRED.filter((k) => !env[k])
    if (missing.length) throw new Error(`vite build (mode ${mode}): missing ${missing.join(', ')}`)
  }
  return {
    plugins: [react()],
    // 127.0.0.1 so the origin matches the Supabase redirect allow-list and the API CORS origin.
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
  }
})
