/** Job and clip shapes from /v1/jobs and /v1/clips (P3), with the Thai wording shown for them. */

export type JobState =
  | 'RECEIVED' | 'SOURCE_VALIDATED' | 'DOWNLOADING' | 'ANALYZING' | 'RENDERING'
  | 'READY_FOR_REVIEW' | 'NEEDS_ACTION' | 'FAILED' | 'CANCELLED'

export type Quota = { reserved: number; settled: number; released: number; outstanding: number }

export type Job = {
  id: string
  state: JobState
  state_version: number
  source: { kind: 'url' | 'local_file'; url: string | null; file_name: string | null }
  environment_id: string
  requested_clips: number
  auto_clips: boolean  // Q-32: the count follows the source
  delete_after_post: boolean  // delete each clip file on the Agent's PC once its post is verified
  planned_clips: number | null
  clip_min_s: number
  clip_max_s: number
  subtitles: boolean
  review_mode: 'review' | 'auto'
  seed: number
  notice: 'INSUFFICIENT_SOURCE' | 'PARTIAL_RENDER' | null
  error: { code: string; detail: string | null } | null
  source_duration_s: number | null
  quota: Quota
  created_at: string
  updated_at: string
  finished_at: string | null
}

export type Check = { name: string; ok: boolean; detail: string | number | null }

export type Clip = {
  id: string
  job_id: string
  index: number
  title: string | null
  start_ms: number
  end_ms: number
  duration_ms: number
  seed: number
  template_version: string
  render_sha256: string
  size_bytes: number
  uploaded: boolean
  // Q-33: 'agent' = the video stays on the Agent's PC (agent_path); the page shows a still instead
  file_location: 'agent' | 'server'
  agent_path: string | null
  agent_file_deleted_at: string | null  // deleted on the Agent's PC after its post (job's delete_after_post)
  preview: 'image' | 'video' | null
  checks: { status: 'passed' | 'failed' | 'skipped'; reason?: string; checks: Check[] } | null
  check_status: 'passed' | 'failed' | 'skipped' | null
  metadata: { version: number; caption: string | null; hashtags: string[] }
  review_mode: 'review' | 'auto'
  approval: { approved: boolean; metadata_version: number | null; mode: 'manual' | 'auto' | null; at: string | null }
}

export type JobDetail = Job & { clips: Clip[] }

export const IN_PROGRESS: JobState[] = ['RECEIVED', 'SOURCE_VALIDATED', 'DOWNLOADING', 'ANALYZING', 'RENDERING']
export const FINISHED: JobState[] = ['READY_FOR_REVIEW', 'NEEDS_ACTION', 'FAILED', 'CANCELLED']

export const STATE: Record<JobState, { text: string; badge: string }> = {
  RECEIVED: { text: 'รอ Agent รับงาน', badge: 'offline' },
  SOURCE_VALIDATED: { text: 'ตรวจต้นฉบับแล้ว', badge: 'stale' },
  DOWNLOADING: { text: 'กำลังดาวน์โหลด', badge: 'stale' },
  ANALYZING: { text: 'กำลังวิเคราะห์', badge: 'stale' },
  RENDERING: { text: 'กำลังสร้างคลิป', badge: 'stale' },
  READY_FOR_REVIEW: { text: 'คลิปพร้อมแล้ว', badge: 'online' },
  NEEDS_ACTION: { text: 'ต้องดำเนินการ', badge: 'warn' },
  FAILED: { text: 'ล้มเหลว', badge: 'revoked' },
  CANCELLED: { text: 'ยกเลิกแล้ว', badge: 'expired' },
}

/** Timeline steps shown on the job page (the server's state order, FR-03). */
export const STEPS: { state: JobState; text: string }[] = [
  { state: 'RECEIVED', text: 'รับงาน' },
  { state: 'SOURCE_VALIDATED', text: 'ตรวจต้นฉบับ' },
  { state: 'DOWNLOADING', text: 'ดาวน์โหลด' },
  { state: 'ANALYZING', text: 'วิเคราะห์' },
  { state: 'RENDERING', text: 'สร้างคลิป' },
  { state: 'READY_FOR_REVIEW', text: 'พร้อมตรวจ' },
]

/** What went wrong and what the customer can do about it. */
const ERRORS: Record<string, string> = {
  INSUFFICIENT_SOURCE: 'ต้นฉบับสั้นเกินกว่าจะตัดเป็นคลิปตามความยาวที่เลือก ไม่ถูกหักโควตา ลองลดความยาวคลิปหรือใช้ต้นฉบับที่ยาวขึ้น',
  QUOTA_EXCEEDED: 'โควตาคลิปของเดือนนี้ไม่พอสำหรับงานนี้ ลดจำนวนคลิปแล้วสร้างงานใหม่ หรือรอรอบโควตาถัดไป',
  SOURCE_NOT_FOUND: 'ไม่พบต้นฉบับ ถ้าเป็นไฟล์บนเครื่อง ให้ตรวจว่าไฟล์อยู่ในโฟลเดอร์วิดีโอของ Agent และชื่อตรงกัน',
  SOURCE_NOT_ACCESSIBLE: 'เปิดต้นฉบับไม่ได้ (ส่วนตัว ต้องล็อกอิน จำกัดอายุหรือประเทศ) ใช้ลิงก์สาธารณะหรือดาวน์โหลดไฟล์เองแล้วสร้างงานแบบไฟล์บนเครื่อง',
  SOURCE_RATE_LIMITED: 'แพลตฟอร์มต้นทางขอให้ชะลอการดาวน์โหลด Agent พักแพลตฟอร์มนี้ชั่วคราว ลองสร้างงานใหม่ภายหลัง',
  SOURCE_LIMIT_EXCEEDED: 'ต้นฉบับยาวหรือใหญ่เกินที่รองรับ',
  UNSUPPORTED_FILE: 'ไฟล์นี้ไม่ใช่วิดีโอที่อ่านได้',
  SOURCE_BLOCKED_ADDRESS: 'ต้นฉบับพาไปยังที่อยู่ภายในเครือข่าย ระบบจึงหยุดก่อนเชื่อมต่อเพื่อความปลอดภัย ใช้ลิงก์วิดีโอสาธารณะลิงก์อื่น',
  UNSUPPORTED_URL:'ลิงก์นี้ไม่รองรับ ใช้ได้เฉพาะ YouTube และ Bilibili',
  DOWNLOADER_ERROR: 'ดาวน์โหลดต้นฉบับไม่สำเร็จ ลองสร้างงานใหม่อีกครั้ง',
  RENDER_FAILED: 'สร้างคลิปไม่สำเร็จ ไม่ถูกหักโควตา',
  RENDER_MISMATCH: 'คลิปที่สร้างได้ไม่ตรงกับที่กำหนด ไม่ถูกหักโควตาส่วนที่ไม่ได้ส่ง',
  SOURCE_CHANGED: 'ต้นฉบับเปลี่ยนไประหว่างทำงาน หยุดงานเพื่อไม่ให้คลิปปนกันสองชุด',
  AGENT_LOST: 'Agent หยุดทำงานระหว่างผลิตหลายครั้ง ตรวจว่าเครื่อง Windows เปิดอยู่และ Agent เชื่อมต่อได้',
  AGENT_ERROR: 'Agent เกิดข้อผิดพลาดระหว่างผลิต ดูบันทึกของ Agent บนเครื่อง Windows',
}

export function errorText(code: string): string {
  return ERRORS[code] ?? 'งานนี้ไม่สำเร็จ'
}

export const CHECK_LABELS: Record<string, string> = {
  readable: 'เปิดเป็นไฟล์วิดีโอ',
  video_stream: 'มีภาพ',
  size_9_16: 'ขนาด 1080×1920 (9:16)',
  audio_stream: 'มีเสียง',
  duration_in_range: 'ความยาวอยู่ในช่วงที่เลือก',
  duration_matches_report: 'ความยาวตรงกับที่ Agent รายงาน',
}

export function mmss(ms: number): string {
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function sourceLabel(job: Job): string {
  return job.source.kind === 'url' ? job.source.url ?? '' : `ไฟล์บนเครื่อง: ${job.source.file_name}`
}
