/** Plans as the API lists them (GET /v1/billing/plans). PO 2026-10-10 (D05): a free trial and three
 * monthly plans; `clips_per_cycle: null` means unlimited (Business). */

export type PlanLimits = { registered_agents: number; concurrent_sessions: number; devices: number; clips_per_cycle: number | null }
export type Plan = {
  code: string; version: number; name: string; price_satang: number; currency: string; interval_days: number
  example_price: boolean
  limits: PlanLimits
}
export type Trial = { days: number; clips: number | null; devices: number; registered_agents: number; price_satang: number }
export type PlanList = { items: Plan[]; trial: Trial; note: string; refund_policy: string }

/** A cycle's clip quota; `limit`/`available` are null on an unlimited plan. */
export type Quota = { limit: number | null; used: number; available: number | null; unlimited?: boolean }

export function baht(satang: number): string {
  return `฿${(satang / 100).toLocaleString('th-TH', { minimumFractionDigits: 0 })}`
}

export function clipsLabel(n: number | null): string {
  return n === null ? 'ไม่จำกัดคลิป' : `${n.toLocaleString('th-TH')} คลิป`
}

/** "ใช้ 12 จาก 1,000 (เหลือ 988)" or "ใช้ 12 คลิป (ไม่จำกัด)". */
export function quotaText(q: Quota): string {
  if (q.limit === null) return `ใช้ ${q.used.toLocaleString('th-TH')} คลิป (ไม่จำกัด)`
  return `ใช้ ${q.used.toLocaleString('th-TH')} จาก ${q.limit.toLocaleString('th-TH')} (เหลือ ${(q.available ?? 0).toLocaleString('th-TH')})`
}

/** Clips still available this cycle; Infinity on an unlimited plan. */
export function clipsLeft(q: Quota | undefined): number {
  if (!q) return 0
  return q.available === null ? Number.POSITIVE_INFINITY : q.available
}
