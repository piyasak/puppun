import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 127.0.0.1 so the origin matches the Supabase redirect allow-list and the API CORS origin.
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
})
