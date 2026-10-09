/** A simulated Agent for browser journeys: real API calls with an Agent session, plus a real sample clip. */
import { expect, type APIRequestContext } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { API } from './helpers'

export function sampleClip(seconds: number): Buffer {
  const out = join(mkdtempSync(join(tmpdir(), 'clipflow-e2e-')), 'clip.mp4')
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', `testsrc2=size=1080x1920:rate=25:duration=${seconds}`,
    '-f', 'lavfi', '-i', `sine=frequency=440:duration=${seconds}`,
    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', out,
  ])
  return readFileSync(out)
}

/** Q-33: the still an Agent sends for a clip it keeps (three frames, 810x480 JPEG). */
export function sampleStill(): Buffer {
  const out = join(mkdtempSync(join(tmpdir(), 'clipflow-e2e-')), 'still.jpg')
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=810x480:rate=1:duration=1',
    '-frames:v', '1', '-q:v', '5', out])
  return readFileSync(out)
}

export class FakeAgent {
  constructor(private request: APIRequestContext, private session: string) {}
  private headers() { return { Authorization: `Bearer ${this.session}` } }
  async event(jobId: string, type: string, payload: Record<string, unknown> = {}) {
    const resp = await this.request.post(`${API}/v1/agent/jobs/${jobId}/events`, {
      headers: this.headers(), data: { event_id: randomUUID().replace(/-/g, ''), type, ...payload },
    })
    expect(resp.status(), await resp.text()).toBe(200)
  }
  async claim() {
    const resp = await this.request.post(`${API}/v1/agent/jobs/claim`, { headers: this.headers(), data: {} })
    return (await resp.json()).job as { id: string; seed: number }
  }
  async deliver(jobId: string, index: number, body: Buffer, durationMs: number) {
    await this.event(jobId, 'clip_rendered', {
      index, start_ms: index * 60_000, end_ms: index * 60_000 + durationMs, duration_ms: durationMs,
      sha256: createHash('sha256').update(body).digest('hex'), size_bytes: body.length,
      template_version: 'tpl-default-v2', title: `ตอนพิเศษ ${index}`,
      caption: `ตอนพิเศษ — ตอนที่ ${index}/2`, hashtags: ['#คลิปสั้น'],
    })
    const resp = await this.request.put(`${API}/v1/agent/jobs/${jobId}/clips/${index}/file`, {
      headers: { ...this.headers(), 'Content-Type': 'video/mp4' }, data: body,
    })
    expect(resp.status(), await resp.text()).toBe(200)
  }
  /** Q-33 delivery: the file stays on the Agent's PC; only its checks and a still reach the server. */
  async deliverKept(jobId: string, index: number, durationMs: number, still: Buffer) {
    await this.event(jobId, 'clip_rendered', {
      index, start_ms: index * 60_000, end_ms: index * 60_000 + durationMs, duration_ms: durationMs,
      sha256: createHash('sha256').update(`kept-${jobId}-${index}`).digest('hex'), size_bytes: 123_456_789,
      template_version: 'tpl-default-v2', title: `ตอนพิเศษ ${index}`, caption: `ตอนพิเศษ — ตอนที่ ${index}`, hashtags: [],
      checks: { status: 'passed', checks: [{ name: 'size_9_16', ok: true, detail: '1080x1920' },
        { name: 'audio_stream', ok: true, detail: 'aac' }, { name: 'duration_in_range', ok: true, detail: durationMs / 1000 }] },
      local_path: ['D:', 'punpun', 'clips', jobId, `clip_${String(index).padStart(2, '0')}.mp4`].join('\\'),
    })
    const resp = await this.request.put(`${API}/v1/agent/jobs/${jobId}/clips/${index}/preview`, {
      headers: { ...this.headers(), 'Content-Type': 'image/jpeg' }, data: still,
    })
    expect(resp.status(), await resp.text()).toBe(200)
  }

  async registerPhone(serial: string) {
    const resp = await this.request.post(`${API}/v1/agent/devices/register`, {
      headers: this.headers(), data: { serial, adb_state: 'device', model: '25078PC3EG', android_version: '15' },
    })
    expect(resp.status(), await resp.text()).toBe(200)
    return (await resp.json()).id as string
  }
}
