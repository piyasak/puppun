/** Telegram notifications (Q-52, PO 2026-10-16): link a chat with a one-time code, choose per phone what each
 * chat hears (posting batched hourly, problems at once, system health, a daily summary), send a test, and see
 * the account numbers the Agent read on Profile. Phase 1.5: people who linked their own Telegram (a private
 * chat with the bot) can press buttons on problem messages; each press is confirmed and audited. */
import { useCallback, useEffect, useState } from 'react'
import { Shell } from '../components/Shell'
import { Alert } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { formatDate } from '../lib/types'

type Chat = { id: string; title: string; kind: string; created_at: string }
type Rule = {
  id: string; chat_ref: string; device_id: string | null
  posting: boolean; problems: boolean; health: boolean; summary: boolean; summary_hour: number
}
type Person = { id: string; name: string; me: boolean; created_at: string }
type Overview = {
  configured: boolean; bot_username: string | null; chats: Chat[]; rules: Rule[]
  phones: { id: string; label: string }[]; people: Person[]
}
type Stat = {
  device_id: string; label: string
  stat: null | {
    account: string | null; followers: number | null; following: number | null; likes: number | null
    video_views: number[]; captured_at: string
  }
}
type Kind = 'posting' | 'problems' | 'health' | 'summary'

const KINDS: [Kind, string][] = [
  ['posting', 'โพสต์สำเร็จ (รวมทุกชั่วโมง)'], ['problems', 'ต้องให้คนดู (ทันที)'], ['health', 'สถานะระบบ'], ['summary', 'สรุปรายวัน'],
]
const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toLocaleString('th-TH'))

export function NotificationsPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [stats, setStats] = useState<Stat[]>([])
  const [link, setLink] = useState<{ link: string; expires_at: string } | null>(null)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await api<Overview>('/v1/notifications'))
      setStats((await api<{ items: Stat[] }>('/v1/notifications/stats')).items)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }, [])
  useEffect(() => { void load() }, [load])

  async function call(fn: () => Promise<unknown>, ok: string) {
    setError('')
    setDone('')
    try {
      await fn()
      setDone(ok)
      await load()
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  function saveRule(rule: Omit<Rule, 'id'>) {
    void call(() => api('/v1/notifications/rules', { method: 'POST', body: rule }), 'บันทึกการตั้งค่าแล้ว')
  }

  async function makeLink() {
    setLink(await api<{ link: string; expires_at: string }>('/v1/notifications/telegram/link', { method: 'POST' }))
  }

  const ruleFor = (chat: string, device: string | null) => data?.rules.find((r) => r.chat_ref === chat && r.device_id === device)

  return (
    <Shell title="การแจ้งเตือน Telegram">
      <section className="card">
        <p className="muted">
          โพสต์สำเร็จส่งรวมทุกชั่วโมง • โพสต์ที่ต้องให้คนดูส่งทันที • สถานะระบบ (Agent ออฟไลน์ โทรศัพท์ไม่พร้อม สิทธิ์โพสต์ใกล้หมด)
          • สรุปรายวันพร้อมยอดผู้ติดตามและยอดดู
        </p>
        {error && <Alert kind="error">{error}</Alert>}
        {done && <Alert kind="success">{done}</Alert>}
        {data && !data.configured && <Alert kind="info">ระบบยังไม่ได้ตั้งค่าบอท Telegram (ผู้ดูแลระบบต้องใส่ค่าบอทที่เซิร์ฟเวอร์ก่อน)</Alert>}
        {data?.configured && (
          <div className="admin-action">
            <button type="button" className="btn btn-primary" onClick={() => void call(makeLink, 'สร้างลิงก์เชื่อมต่อแล้ว')}>เชื่อม Telegram</button>
            {link && (
              <span>
                เปิด <a href={link.link} target="_blank" rel="noreferrer">{link.link}</a> แล้วกด Start ในแชตที่ต้องการ
                (สำหรับกลุ่ม: เพิ่มบอทในกลุ่มก่อน แล้วเปิดลิงก์นี้) • ใช้ได้ถึง {formatDate(link.expires_at)}
              </span>
            )}
          </div>
        )}
      </section>

      {data?.configured && (
        <section className="card" aria-labelledby="people-title">
          <h2 id="people-title">คนที่กดปุ่มใน Telegram ได้</h2>
          <p className="muted">
            ข้อความที่ต้องให้คนดูมีปุ่ม ลองใหม่ / ยกเลิกโพสต์ / ตรวจหน้าจอ / พบโพสต์แล้ว / ไม่ได้โพสต์ ทุกปุ่มต้องกดยืนยันอีกครั้ง
            และถูกบันทึกในประวัติ การยืนยันผลโพสต์ต้องพิมพ์หลักฐานตอบกลับบอท กดได้เฉพาะคนที่เปิดลิงก์ เชื่อม Telegram
            ในแชตส่วนตัวกับบอท (ลิงก์ในกลุ่มเชื่อมแค่กลุ่ม ไม่เชื่อมตัวคน)
          </p>
          <ul className="rows">
            {data.people.length === 0 && <li className="row muted">ยังไม่มี</li>}
            {data.people.map((p) => (
              <li key={p.id} className="row" data-testid="telegram-person">
                <div className="row-main">
                  <strong>{p.name}</strong>
                  <span className="muted">{p.me ? 'บัญชีของคุณ • ' : ''}เชื่อมเมื่อ {formatDate(p.created_at)}</span>
                </div>
                <button type="button" className="btn btn-danger-outline btn-small"
                  onClick={() => void call(() => api(`/v1/notifications/telegram/people/${p.id}`, { method: 'DELETE' }), 'ยกเลิกสิทธิ์กดปุ่มแล้ว')}>
                  ยกเลิกสิทธิ์กดปุ่ม
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data?.chats.map((chat) => (
        <section key={chat.id} className="card" data-testid="telegram-chat">
          <h2>{chat.title} <span className="muted">({chat.kind === 'private' ? 'แชตส่วนตัว' : 'กลุ่ม'})</span></h2>
          <div className="admin-action">
            <button type="button" className="btn btn-secondary btn-small"
              onClick={() => void call(() => api('/v1/notifications/test', { method: 'POST', body: { chat_ref: chat.id } }), 'ส่งข้อความทดสอบแล้ว (ภายใน 1 นาที)')}>
              ส่งข้อความทดสอบ
            </button>
            <button type="button" className="btn btn-danger-outline btn-small"
              onClick={() => void call(() => api(`/v1/notifications/telegram/chats/${chat.id}`, { method: 'DELETE' }), 'ยกเลิกการเชื่อมแล้ว')}>
              ยกเลิกการเชื่อม
            </button>
          </div>
          <table>
            <thead>
              <tr><th>โทรศัพท์</th>{KINDS.map(([, label]) => <th key={label}>{label}</th>)}<th>เวลาสรุป</th></tr>
            </thead>
            <tbody>
              {[{ id: null as string | null, label: 'ทุกเครื่อง' }, ...data.phones].map((phone) => {
                const rule = ruleFor(chat.id, phone.id)
                const base = rule ?? {
                  chat_ref: chat.id, device_id: phone.id, posting: false, problems: false, health: false, summary: false, summary_hour: 21,
                }
                return (
                  <tr key={phone.id ?? 'all'}>
                    <td>{phone.label}{!rule && phone.id && <span className="muted"> (ตามทุกเครื่อง)</span>}</td>
                    {KINDS.map(([key, label]) => (
                      <td key={key}>
                        <input type="checkbox" aria-label={`${phone.label}: ${label}`} checked={!!rule?.[key]}
                          onChange={(e) => saveRule({ ...base, [key]: e.target.checked })} />
                      </td>
                    ))}
                    <td>
                      <select aria-label={`${phone.label}: เวลาสรุป`} value={base.summary_hour}
                        onChange={(e) => saveRule({ ...base, summary_hour: Number(e.target.value) })}>
                        {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
                      </select>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      ))}

      <section className="card" aria-labelledby="stats-title">
        <h2 id="stats-title">ยอดบัญชีล่าสุด</h2>
        <p className="muted">Agent 0.9.0 ขึ้นไปอ่านจากหน้าโปรไฟล์ TikTok วันละ 2 ครั้งเมื่อโทรศัพท์ว่าง (ดูอย่างเดียว ไม่โพสต์)</p>
        <ul className="rows">{stats.map((s) => (
          <li key={s.device_id} className="row"><div className="row-main">
            <strong>{s.label}</strong>
            {s.stat ? (
              <span className="muted">
                ผู้ติดตาม {num(s.stat.followers)} • กำลังติดตาม {num(s.stat.following)} • ถูกใจ {num(s.stat.likes)}
                {' '}• ยอดดูวิดีโอล่าสุด {s.stat.video_views.length} คลิป รวม {num(s.stat.video_views.reduce((a, b) => a + b, 0))}
                {' '}• อ่านเมื่อ {formatDate(s.stat.captured_at)}
              </span>
            ) : <span className="muted">ยังไม่มีข้อมูล</span>}
          </div></li>
        ))}</ul>
      </section>
    </Shell>
  )
}
