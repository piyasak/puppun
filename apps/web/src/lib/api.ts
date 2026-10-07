import { API_URL, supabase } from './supabase'

export type Me = {
  user: { id: string; email: string; username: string }
  workspace: { id: string; name: string; timezone: string }
  role: string
  rights_declaration: { version: string; accepted_at: string } | null
}

export class ApiError extends Error {
  status: number
  code: string
  requestId?: string
  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message)
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

/** Calls the ClipFlow API with the Supabase access token in the Authorization header. */
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  const resp = await fetch(`${API_URL}${path}`, {
    method: init.method ?? 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  const text = await resp.text()
  const json = text ? JSON.parse(text) : null
  if (!resp.ok) {
    throw new ApiError(resp.status, json?.code ?? 'HTTP_ERROR', json?.message ?? 'เกิดข้อผิดพลาด', json?.request_id)
  }
  return json as T
}
