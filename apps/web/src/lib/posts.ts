/** Post (schedule item) states as shown in short lists: the calendar and the dashboard (P4.6, E-47). */
export const POST_STATE: Record<string, { text: string; badge: string }> = {
  SCHEDULED: { text: 'รอเวลาโพสต์', badge: 'active' },
  NEEDS_ACTION: { text: 'ต้องดำเนินการ', badge: 'warn' },
  CANCELLED: { text: 'ยกเลิก', badge: 'expired' },
  SKIPPED: { text: 'ข้าม', badge: 'expired' },
  CLAIMED: { text: 'Agent รับงานแล้ว', badge: 'stale' },
  TRANSFERRING: { text: 'กำลังส่งไฟล์', badge: 'stale' },
  PREPARING: { text: 'กำลังเตรียม', badge: 'stale' },
  SUBMITTING: { text: 'กำลังโพสต์', badge: 'stale' },
  VERIFYING: { text: 'กำลังตรวจผล', badge: 'stale' },
  VERIFIED_SUCCESS: { text: 'โพสต์สำเร็จ', badge: 'online' },
  UNKNOWN: { text: 'ไม่ทราบผล', badge: 'revoked' },
  DRY_RUN_DONE: { text: 'ทดสอบเสร็จ (ไม่ได้โพสต์จริง)', badge: 'expired' },
}

/** Not finished yet: waiting for its time or on its way to the phone. */
export const UPCOMING = ['SCHEDULED', 'CLAIMED', 'TRANSFERRING', 'PREPARING', 'SUBMITTING', 'VERIFYING']

export const TZ = 'Asia/Bangkok'
