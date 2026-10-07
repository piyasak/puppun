// Fails the build when the production bundle is missing the app's own code.
// Guards against the 2026-10-08 regression where a module-scope throw let the bundler drop
// every route while `vite build` still reported success.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const dir = 'dist/assets'
const js = readdirSync(dir).filter((f) => f.endsWith('.js')).map((f) => readFileSync(join(dir, f), 'utf8')).join('\n')
const required = ['/v1/me', '/v1/onboarding', '/v1/environments', '/v1/agent-tokens', '/v1/agents', '/v1/devices']
const missing = required.filter((s) => !js.includes(s))
if (missing.length) {
  console.error(`bundle check failed: missing ${missing.join(', ')}`)
  process.exit(1)
}
console.log(`bundle check ok (${required.length} API routes present)`)
