import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatDate } from '../lib/types'
import { Alert } from './ui'

/* Q-42: which TikTok accounts may post for real. Grants are given by the punpun team; without one,
   every post stops before Post (dry run). */

type Grant = { id: string; account: string; visibility: string; used_posts: number; max_posts: number
  remaining: number; expires_at: string; status: string }

export function PostingGrants() {
  const [grants, setGrants] = useState<Grant[] | null>(null)

  useEffect(() => {
    api<{ items: Grant[] }>('/v1/devices/posting-grants').then((r) => setGrants(r.items)).catch(() => setGrants([]))
  }, [])

  if (grants === null) return null
  const active = grants.filter((g) => g.status === 'active')
  if (active.length === 0) {
    return (
      <Alert kind="info">
        โหมดทดสอบ: Agent ส่งคลิปเข้าโทรศัพท์แล้ว<strong>หยุดก่อนกดโพสต์</strong> ยังไม่โพสต์จริง
        ติดต่อทีมงาน punpun เพื่อขอเปิดโพสต์จริงสำหรับบัญชี TikTok ของคุณ
      </Alert>
    )
  }
  return (
    <Alert kind="success">
      <span data-testid="posting-grants">
        โพสต์จริงเปิดสำหรับ{' '}
        {active.map((g, i) => (
          <span key={g.id}>{i > 0 && ', '}<strong>@{g.account}</strong> (แบบเฉพาะฉัน เหลือ {g.remaining} โพสต์ ถึง {formatDate(g.expires_at)})</span>
        ))}
        {' '}• ต้องใช้ Agent 0.4.0 ขึ้นไป • บัญชีอื่นยังหยุดก่อนกดโพสต์
      </span>
    </Alert>
  )
}
