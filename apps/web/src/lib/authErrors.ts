import type { AuthError } from '@supabase/supabase-js'

/** Thai messages for Supabase Auth errors. Login failures never say which part was wrong. */
export function authMessage(error: AuthError | null | undefined): string {
  if (!error) return ''
  switch (error.code) {
    case 'invalid_credentials':
      return 'อีเมลหรือรหัสผ่านไม่ถูกต้อง'
    case 'email_not_confirmed':
      return 'กรุณายืนยันอีเมลก่อน โดยกดลิงก์ในอีเมลที่เราส่งให้'
    case 'weak_password':
      return 'รหัสผ่านสั้นหรือง่ายเกินไป (อย่างน้อย 10 ตัวอักษร)'
    case 'same_password':
      return 'รหัสผ่านใหม่ต้องไม่ซ้ำกับรหัสเดิม'
    case 'over_email_send_rate_limit':
    case 'over_request_rate_limit':
      return 'ส่งคำขอบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่'
    case 'signup_disabled':
      return 'ขณะนี้ปิดรับสมัครสมาชิก'
    case 'validation_failed':
      return 'ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบอีเมล'
    default:
      return 'เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง'
  }
}
