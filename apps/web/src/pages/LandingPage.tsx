/*
 * Marketing landing page at / for visitors who are not signed in (signed-in users get the dashboard).
 * "Linear / Modern" at full strength (uithem.txt): moving ambient light, gradient type, scroll reveal,
 * a light hero parallax and cursor spotlights on cards; everything stops with prefers-reduced-motion.
 * Copy states only what the product does today (no prices: D05 is open; no testimonials or logos).
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ThemeToggle } from '../components/ThemeToggle'
import './landing.css'

const STEPS = [
  { n: '01', title: 'ใส่ต้นฉบับ', text: 'วางลิงก์ YouTube หรือ Bilibili ของคุณ หรือเลือกไฟล์วิดีโอบนเครื่อง ไม่ต้องอัปโหลดไฟล์ใหญ่ขึ้นเว็บ' },
  { n: '02', title: 'ตัดเป็นคลิปแนวตั้ง', text: 'Agent บนเครื่อง Windows ของคุณหาจังหวะพักเสียง ตัดเป็นคลิป 9:16 ใส่ชื่อตอนและซับไทยที่อ่านง่าย' },
  { n: '03', title: 'ตรวจและอนุมัติ', text: 'ดูตัวอย่าง แก้แคปชันและแฮชแท็ก แล้วกดอนุมัติ ทุกครั้งที่แก้ข้อความ ระบบจะรอให้อนุมัติใหม่ก่อนโพสต์' },
  { n: '04', title: 'ตั้งเวลา โพสต์ และยืนยันผล', text: 'โพสต์ผ่านโทรศัพท์ Android ของคุณตามช่วงเวลาที่กำหนด แล้วตรวจว่าโพสต์ขึ้นบัญชีที่ถูกต้องจริง' },
]

const AUDIENCES = [
  { tag: 'ร้านค้า / SME', title: 'คลิปขายของทุกวัน โดยไม่ต้องนั่งตัดเอง', text: 'เอาไลฟ์หรือวิดีโอรีวิวยาว ๆ มาแบ่งเป็นคลิปสั้น ตั้งเวลาโพสต์ทั้งสัปดาห์ในครั้งเดียว' },
  { tag: 'ครีเอเตอร์', title: 'ขยายช่องจาก YouTube ไป TikTok', text: 'ตอนยาวหนึ่งตอนกลายเป็นหลายคลิป เลือกช่วงซ้ำได้ด้วย seed เดิม และควบคุมข้อความทุกคลิปเอง' },
  { tag: 'เอเจนซี่ / ทีม', title: 'หลายโทรศัพท์ หลายบัญชี ในที่เดียว', text: 'แยกเครื่องและบัญชีของลูกค้าแต่ละราย เห็นตารางโพสต์รวม และรายการที่ต้องตัดสินใจในหน้าเดียว' },
]

const FAQ = [
  { q: 'ต้องมีอะไรบ้าง?', a: 'คอมพิวเตอร์ Windows สำหรับติดตั้ง Agent, โทรศัพท์ Android ที่เปิด USB debugging และแอป TikTok ที่ล็อกอินบัญชีของคุณไว้แล้ว' },
  { q: 'วิดีโอของฉันถูกส่งขึ้นเซิร์ฟเวอร์ไหม?', a: 'การดาวน์โหลด ตัด และเรนเดอร์ทำบนเครื่องของคุณ ระบบรับเฉพาะคลิปที่ตัดเสร็จแล้วมาให้ดูตัวอย่างและอนุมัติ และลบไฟล์ตามระยะเวลาเก็บของแพ็กเกจ' },
  { q: 'จะโพสต์ซ้ำหรือผิดบัญชีได้ไหม?', a: 'ก่อนโพสต์ Agent ตรวจว่าโทรศัพท์ล็อกอินบัญชีที่ตั้งไว้ ถ้าไม่ตรงจะหยุดทันที และถ้าไม่แน่ใจว่าโพสต์สำเร็จหรือไม่ ระบบจะหยุดรอให้คุณตรวจ ไม่ส่งซ้ำเอง' },
  { q: 'โทรศัพท์รุ่นไหนใช้ได้?', a: 'ตอนนี้อยู่ในช่วงทดสอบกับรุ่นที่ผ่านการตรวจแล้ว เครื่องที่ยังไม่ได้ทดสอบจะถูกแจ้งในหน้าโทรศัพท์และไม่ถูกใช้โพสต์' },
  { q: 'ใช้กับวิดีโอของคนอื่นได้ไหม?', a: 'ไม่ได้ ใช้ได้เฉพาะเนื้อหาที่คุณเป็นเจ้าของหรือได้รับอนุญาต ระบบไม่ลบลายน้ำและไม่ดัดแปลงภาพเพื่อหลบการตรวจของแพลตฟอร์ม' },
  { q: 'คลิปยาวเท่าไร?', a: 'ค่าเริ่มต้น 3–5 นาที และเลือก 1–3 นาที หรือ 30–60 วินาทีได้ ถ้าต้นฉบับสั้นเกิน ระบบแจ้งจำนวนที่ทำได้จริง ไม่เติมคลิปซ้ำให้ครบ' },
]

/** Fade/slide sections in once as they enter the viewport. */
function useReveal(root: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current
    if (!el) return
    const items = [...el.querySelectorAll<HTMLElement>('.lp-reveal')]
    if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      items.forEach((i) => i.classList.add('in'))
      return
    }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target) }
    }, { threshold: 0.15 })
    items.forEach((i) => io.observe(i))
    return () => io.disconnect()
  }, [root])
}

/** Hero fades and settles as the page scrolls (0 → 1 over the first half screen). */
function useHeroParallax(hero: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = hero.current
    if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => el.style.setProperty('--p', String(Math.min(1, scrollY / (innerHeight * 0.5)))))
    }
    addEventListener('scroll', onScroll, { passive: true })
    return () => { removeEventListener('scroll', onScroll); cancelAnimationFrame(frame) }
  }, [hero])
}

/** Cursor spotlight on cards: one listener for the whole page. */
function onSpotlight(e: React.PointerEvent<HTMLElement>) {
  const card = (e.target as HTMLElement).closest<HTMLElement>('.lp-card')
  if (!card) return
  const r = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${e.clientX - r.left}px`)
  card.style.setProperty('--my', `${e.clientY - r.top}px`)
}

export function LandingPage() {
  const page = useRef<HTMLDivElement>(null)
  const hero = useRef<HTMLElement>(null)
  const [menu, setMenu] = useState(false)
  useReveal(page)
  useHeroParallax(hero)
  useEffect(() => { document.title = 'punpun — ตัดคลิปสั้นและตั้งเวลาโพสต์ TikTok จากวิดีโอของคุณ' }, [])

  return (
    <div className="lp" ref={page} onPointerMove={onSpotlight}>
      <div className="lp-ambient" aria-hidden="true"><span className="lp-blob b1" /><span className="lp-blob b2" /><span className="lp-blob b3" /></div>

      <header className="lp-nav">
        <a className="auth-brand lp-brand" href="#top"><span className="brand-mark" aria-hidden="true">p</span> punpun</a>
        <nav aria-label="ส่วนของหน้า" className={`lp-links${menu ? ' open' : ''}`} onClick={() => setMenu(false)}>
          <a href="#how">ทำงานอย่างไร</a><a href="#features">จุดเด่น</a><a href="#who">เหมาะกับใคร</a><a href="#faq">คำถามที่พบบ่อย</a>
        </nav>
        <div className="lp-nav-actions">
          <ThemeToggle />
          <Link to="/login" className="btn btn-secondary btn-small lp-hide-sm">เข้าสู่ระบบ</Link>
          <Link to="/signup" className="btn btn-primary btn-small">ทดลองใช้ฟรี</Link>
          <button type="button" className="icon-btn lp-menu" aria-expanded={menu} aria-label="เมนูหน้า" onClick={() => setMenu((m) => !m)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              {menu ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
      </header>

      <main id="top">
        <section className="lp-hero" ref={hero} aria-labelledby="lp-title">
          <div className="lp-hero-copy">
            <p className="lp-eyebrow">วิดีโอยาว → คลิปสั้น → TikTok</p>
            <h1 id="lp-title" className="lp-display">
              {/* Thai has no spaces: each phrase stays whole, lines break only between phrases. */}
              <span className="lp-nw">ตัดวิดีโอยาว</span> <span className="lp-nw">เป็นคลิปสั้น</span><br />
              <span className="lp-shimmer"><span className="lp-nw">แล้วโพสต์</span> <span className="lp-nw">ตามเวลาให้เอง</span></span>
            </h1>
            <p className="lp-lead">punpun ตัดคลิปแนวตั้งพร้อมซับไทยบนเครื่องของคุณ ให้คุณตรวจและอนุมัติ แล้วโพสต์ผ่านโทรศัพท์ของคุณตามตาราง พร้อมยืนยันว่าโพสต์ขึ้นบัญชีที่ถูกต้อง</p>
            <div className="lp-cta">
              <Link to="/signup" className="btn btn-primary lp-btn-lg">ทดลองใช้ฟรี 30 วัน</Link>
              <a href="#how" className="btn btn-secondary lp-btn-lg">ดูวิธีทำงาน</a>
            </div>
            <p className="lp-note">ไม่ต้องใช้บัตรเครดิตตอนสมัคร</p>
          </div>

          <div className="lp-hero-visual" aria-hidden="true">
            <div className="lp-phone">
              <div className="lp-phone-screen">
                <div className="lp-clip-bars"><i /><i /><i /></div>
                <div className="lp-clip-sub">ตอนพิเศษ — ตอนที่ 3/5</div>
                <div className="lp-clip-cap">ซับไทยอ่านง่าย ไม่ล้นจอ</div>
              </div>
            </div>
            <div className="lp-float lp-float-a">
              <span className="badge badge-active">อนุมัติแล้ว</span>
              <b>คลิป 3 • 3:42</b><span className="muted">ผ่านการตรวจไฟล์ 9:16</span>
            </div>
            <div className="lp-float lp-float-b">
              <span className="lp-mono">ตารางโพสต์ • เวลาไทย</span>
              <ol className="lp-slots">
                <li className="done"><b>19:00</b> ยืนยันผลแล้ว</li>
                <li className="now"><b>21:00</b> รอเวลาโพสต์</li>
                <li><b>09:00</b> พรุ่งนี้</li>
              </ol>
            </div>
          </div>
        </section>

        <div className="lp-rule" aria-hidden="true" />

        <section id="how" className="lp-section" aria-labelledby="how-title">
          <p className="lp-eyebrow lp-reveal">ทำงานอย่างไร</p>
          <h2 id="how-title" className="lp-h2 lp-reveal">สี่ขั้น จากวิดีโอยาวถึงโพสต์ที่ยืนยันแล้ว</h2>
          <ol className="lp-steps">
            {STEPS.map((s) => (
              <li key={s.n} className="lp-card lp-reveal"><span className="lp-step-n">{s.n}</span><h3>{s.title}</h3><p>{s.text}</p></li>
            ))}
          </ol>
        </section>

        <section id="features" className="lp-section" aria-labelledby="feat-title">
          <p className="lp-eyebrow lp-reveal">จุดเด่น</p>
          <h2 id="feat-title" className="lp-h2 lp-reveal">ทำให้โพสต์สม่ำเสมอ โดยไม่ต้องลุ้นว่าจะพลาด</h2>
          <div className="lp-bento">
            <article className="lp-card lp-b-hero lp-reveal">
              <h3>ตั้งเวลาแบบไม่รวน</h3>
              <p>กำหนดเวลาเริ่ม ระยะห่าง และช่วงเวลาที่โพสต์ได้ เกินช่วงจะเลื่อนไปวันถัดไปเอง ถ้าโทรศัพท์ออฟไลน์ ระบบเลื่อนตามระยะเดิมหรือข้ามรอบตามที่เลือก ไม่โพสต์รวดเดียวตอนกลับมาออนไลน์</p>
              <div className="lp-week">
                {['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา'].map((d, i) => (
                  <div key={d} className="lp-day"><span>{d}</span>{[0, 1, 2].map((k) => <i key={k} className={(i + k) % 3 === 0 ? 'on' : ''} />)}</div>
                ))}
              </div>
            </article>
            <article className="lp-card lp-b2 lp-reveal"><h3>ไม่โพสต์ซ้ำ</h3><p>ถ้า Agent หลุดหลังกดโพสต์ ระบบจะหยุดรอให้คุณตรวจ ไม่ส่งซ้ำเอง</p></article>
            <article className="lp-card lp-b2 lp-reveal"><h3>ตรวจบัญชีก่อนทุกครั้ง</h3><p>โทรศัพท์ล็อกอินผิดบัญชี = หยุดก่อนเปิดคลิป</p></article>
            <article className="lp-card lp-b3 lp-reveal"><h3>คุณอนุมัติก่อนเสมอ</h3><p>โพสต์เฉพาะข้อความเวอร์ชันที่อนุมัติ แก้เมื่อไรต้องอนุมัติใหม่ หรือเลือกอนุมัติอัตโนมัติเฉพาะคลิปที่ผ่านการตรวจไฟล์ทุกข้อ</p></article>
            <article className="lp-card lp-b3 lp-reveal"><h3>ไฟล์อยู่บนเครื่องคุณ</h3><p>ดาวน์โหลดและเรนเดอร์บนคอมพิวเตอร์ของคุณ Agent เชื่อมต่อออกไปหาเซิร์ฟเวอร์เท่านั้น ไม่เปิดพอร์ตรับจากภายนอก</p></article>
          </div>
        </section>

        <section id="who" className="lp-section" aria-labelledby="who-title">
          <p className="lp-eyebrow lp-reveal">เหมาะกับใคร</p>
          <h2 id="who-title" className="lp-h2 lp-reveal">ทำมาเพื่อคนที่มีวิดีโอยาวอยู่แล้ว</h2>
          <div className="lp-audiences">
            {AUDIENCES.map((a) => (
              <article key={a.tag} className="lp-card lp-reveal"><span className="lp-tag">{a.tag}</span><h3>{a.title}</h3><p>{a.text}</p></article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-trust lp-reveal" aria-labelledby="trust-title">
          <div className="lp-card">
            <h2 id="trust-title" className="lp-h3">ใช้อย่างรับผิดชอบ</h2>
            <ul>
              <li>ใช้ได้เฉพาะเนื้อหาที่คุณเป็นเจ้าของหรือได้รับอนุญาต (ยืนยันตอนสมัคร)</li>
              <li>ไม่ลบลายน้ำ ไม่ดัดแปลงภาพเพื่อหลบการตรวจของแพลตฟอร์ม</li>
              <li>ไม่ใช้ proxy หรือเปลี่ยน IP เพื่อหลบการจำกัดของแหล่งวิดีโอ</li>
              <li>โพสต์ผ่านแอป TikTok ในโทรศัพท์และบัญชีของคุณเอง</li>
            </ul>
          </div>
        </section>

        <section id="faq" className="lp-section" aria-labelledby="faq-title">
          <p className="lp-eyebrow lp-reveal">คำถามที่พบบ่อย</p>
          <h2 id="faq-title" className="lp-h2 lp-reveal">ก่อนเริ่มใช้</h2>
          <div className="lp-faq">
            {FAQ.map((f) => (
              <details key={f.q} className="lp-card lp-reveal"><summary>{f.q}</summary><p>{f.a}</p></details>
            ))}
          </div>
        </section>

        <section className="lp-final lp-reveal" aria-labelledby="final-title">
          <h2 id="final-title" className="lp-display lp-display-sm"><span className="lp-nw">เริ่มจากวิดีโอ</span> <span className="lp-nw">ที่คุณมีอยู่แล้ว</span></h2>
          <p className="lp-lead">ทดลองใช้ฟรี 30 วัน แล้วเลือกแพ็กเกจที่เหมาะกับจำนวนคลิปและโทรศัพท์ของคุณหลังสมัคร</p>
          <div className="lp-cta lp-cta-center">
            <Link to="/signup" className="btn btn-primary lp-btn-lg">สมัครและทดลองใช้ฟรี</Link>
            <Link to="/login" className="btn btn-secondary lp-btn-lg">มีบัญชีแล้ว เข้าสู่ระบบ</Link>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <span className="auth-brand lp-brand"><span className="brand-mark" aria-hidden="true">p</span> punpun</span>
        <span className="muted">ตัดคลิปสั้นและตั้งเวลาโพสต์จากวิดีโอของคุณ</span>
      </footer>
    </div>
  )
}
