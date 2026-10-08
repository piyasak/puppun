export type Limits = {
  registered_agent_limit: number
  concurrent_session_limit: number
  device_limit: number
}

export type Environment = Limits & { id: string; name: string; created_at: string }

export type Usage = {
  plan: { code: string; version: number; name: string; is_demo: boolean; status: string }
  caps: Limits
  allocated: Limits
  in_use: Limits
  clips: { period: string; limit: number; used: number; available: number }
}

export type AgentToken = {
  id: string
  name: string
  prefix: string
  environment: { id: string; name: string }
  status: 'active' | 'expired' | 'revoked'
  created_at: string
  expires_at: string
  revoked_at: string | null
  last_used_at: string | null
  rotated_from_id: string | null
}

export type NewAgentToken = AgentToken & { token: string }

export const LIMIT_LABELS: Record<keyof Limits, string> = {
  registered_agent_limit: 'Agent ที่ลงทะเบียนได้',
  concurrent_session_limit: 'Session พร้อมกัน',
  device_limit: 'โทรศัพท์',
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('th-TH', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok' })
    .format(new Date(iso))
}
