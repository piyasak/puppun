import { defineConfig } from '@playwright/test'

/*
 * Browser E2E against LOCAL services only: local Supabase (supabase CLI, Docker) + Mailpit,
 * the ClipFlow API on a dedicated e2e database, and the Vite dev server.
 * Run through `py tasks.py test-e2e`, which prepares the environment variables below.
 * Never point this at the cloud Supabase project: it creates accounts.
 */
const env = process.env
const supabaseUrl = env.E2E_SUPABASE_URL ?? 'http://127.0.0.1:54321'
if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(supabaseUrl)) {
  throw new Error(`E2E must use a local Supabase, got ${supabaseUrl}`)
}

export default defineConfig({
  testDir: './e2e',
  outputDir: '../../var/evidence/e2e/results',
  reporter: [['list'], ['html', { outputFolder: '../../var/evidence/e2e/report', open: 'never' }]],
  timeout: 60_000,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    channel: 'msedge', // installed with Windows; no browser download needed
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'th-TH',
  },
  webServer: [
    {
      command: `"${env.E2E_PYTHON}" -m uvicorn clipflow_api.app:app --host 127.0.0.1 --port 8001`,
      url: 'http://127.0.0.1:8001/healthz',
      cwd: '../..',
      reuseExistingServer: false,
      env: {
        APP_ENV: 'test',
        DATABASE_URL: env.E2E_DATABASE_URL ?? '',
        SUPABASE_URL: supabaseUrl,
        WEB_ORIGIN: 'http://127.0.0.1:5173',
      },
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      env: {
        VITE_SUPABASE_URL: supabaseUrl,
        VITE_SUPABASE_PUBLISHABLE_KEY: env.E2E_SUPABASE_PUBLISHABLE_KEY ?? '',
        VITE_API_URL: 'http://127.0.0.1:8001',
      },
    },
  ],
})
