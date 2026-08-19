import { useEffect, useRef, useState } from 'react'

/**
 * Ported from the validated HTML prototype (ghumi_transition_demo.html).
 * Behavior is unchanged: scroll through the hero, the route line draws via
 * stroke-dashoffset, a plane rides it and takes off near the end of the
 * dusk→paper transition band. See Design_Spec_v3/v4 §3 for the spec this
 * implements.
 */
export default function LandingPage() {
  const bandRef = useRef<HTMLDivElement>(null)
  const [lineOffset, setLineOffset] = useState(200)
  const [showAgentText, setShowAgentText] = useState(false)
  const [planeStyle, setPlaneStyle] = useState<{ top: string; opacity: number; takeoff: boolean }>({
    top: '0%',
    opacity: 0,
    takeoff: false,
  })

  useEffect(() => {
    const TAKEOFF_AT = 0.9

    function onScroll() {
      const band = bandRef.current
      if (!band) return
      const rect = band.getBoundingClientRect()
      const vh = window.innerHeight
      let progress = (vh - rect.top) / (vh + rect.height)
      progress = Math.max(0, Math.min(1, progress))

      setLineOffset(200 - progress * 200)
      setShowAgentText(progress > 0.15)

      if (progress >= TAKEOFF_AT) {
        setPlaneStyle((s) => ({ ...s, takeoff: true }))
      } else {
        const rideProgress = Math.min(progress / TAKEOFF_AT, 1)
        setPlaneStyle({
          top: `${rideProgress * 92}%`,
          opacity: progress > 0.05 ? 1 : 0,
          takeoff: false,
        })
      }
    }

    document.addEventListener('scroll', onScroll)
    onScroll()
    return () => document.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div>
      {/* ---------- HERO ---------- */}
      <section className="relative h-screen flex flex-col items-center justify-center overflow-hidden bg-[linear-gradient(180deg,#2c463c_0%,#1e3a30_45%,#16332B_100%)]">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,rgba(201,138,59,0.18),transparent_55%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(22,51,43,0)_0%,rgba(22,51,43,0.55)_65%,#16332B_100%)]" />

        <h1
          className="relative z-10 font-display font-semibold text-paper text-center leading-[0.88] tracking-tight"
          style={{
            fontSize: 'clamp(64px, 13vw, 190px)',
            textShadow:
              '0 1px 0 rgba(255,255,255,0.4), 0 2px 0 rgba(0,0,0,0.15), 0 6px 0 rgba(22,51,43,0.5), 0 14px 24px rgba(0,0,0,0.55), 0 30px 60px rgba(0,0,0,0.4)',
          }}
        >
          Ghumi
        </h1>
        <p className="relative z-10 font-display italic font-light text-[15px] text-paper/65 mt-3.5">
          a trip, worked out for you
        </p>

        {/* Glass boarding-pass card */}
        <div className="relative z-10 mt-12 w-[min(360px,84vw)] rounded-2xl p-6 border border-paper/20 shadow-2xl bg-brand/55 backdrop-blur-xl">
          <div className="flex justify-between items-baseline">
            <span className="font-display text-2xl text-paper">BLR</span>
            <span className="text-brass text-base self-center">✈</span>
            <span className="font-display text-2xl text-paper">HND</span>
          </div>
          <div className="my-4 h-px bg-[repeating-linear-gradient(90deg,rgba(246,244,239,0.35)_0_6px,transparent_6px_12px)]" />
          <div className="flex justify-between">
            <Field label="Traveler" value="A. Rao" />
            <Field label="Dates" value="12–19 Mar" />
            <Field label="Status" value="Planning" />
          </div>
        </div>

        <div className="absolute bottom-7 left-1/2 -translate-x-1/2 font-mono text-[10px] tracking-widest text-paper/60 uppercase">
          scroll ↓
        </div>
      </section>

      {/* ---------- TRANSITION BAND ---------- */}
      <section
        ref={bandRef}
        className="relative h-[34vh] overflow-hidden flex items-start justify-center"
        style={{ background: 'linear-gradient(180deg, #16332B 0%, #16332B 40%, #F6F4EF 100%)' }}
      >
        <svg viewBox="0 0 2 200" preserveAspectRatio="none" className="absolute top-0 left-1/2 -translate-x-1/2 h-full w-0.5">
          <line x1="1" y1="0" x2="1" y2="200" stroke="#F6F4EF" strokeWidth="2" strokeDasharray="6 6" strokeDashoffset={lineOffset} />
        </svg>

        <div
          className={`absolute top-[6%] left-1/2 -translate-x-1/2 font-mono text-[11px] tracking-wider text-paper/85 whitespace-nowrap transition-opacity duration-500 ${
            showAgentText ? 'opacity-100' : 'opacity-0'
          }`}
        >
          BUDGET AGENT<span className="text-brass mx-1.5">→</span>SEARCH AGENT<span className="text-brass mx-1.5">→</span>RANKING AGENT
        </div>

        <div
          className="absolute left-1/2 top-0 w-5 h-5 flex items-center justify-center text-base text-paper z-10 will-change-transform"
          style={{
            textShadow: '0 2px 6px rgba(0,0,0,0.4)',
            transition: planeStyle.takeoff
              ? 'transform 0.9s cubic-bezier(0.55,0.02,0.2,1), opacity 0.9s ease 0.2s'
              : 'opacity 0.4s ease',
            transform: planeStyle.takeoff
              ? 'translate(calc(-50% + 90px), calc(-50% - 100px)) rotate(35deg) scale(1.6)'
              : `translate(-50%, -50%) rotate(90deg)`,
            top: planeStyle.takeoff ? undefined : planeStyle.top,
            opacity: planeStyle.takeoff ? 0 : planeStyle.opacity,
          }}
        >
          ✈
        </div>
      </section>

      {/* ---------- HOW IT WORKS ---------- */}
      <section className="bg-paper px-6 pt-10 pb-24">
        <div className="max-w-3xl mx-auto">
          <span className="block text-center font-mono text-[11px] tracking-wider text-brass uppercase mb-1.5">How it works</span>
          <h2 className="font-display font-medium text-center text-ink mb-14" style={{ fontSize: 'clamp(28px,4vw,40px)' }}>
            Three agents, one itinerary
          </h2>

          <div className="grid grid-cols-3 relative">
            <div className="absolute top-[34px] left-[16.6%] right-[16.6%] h-0.5 bg-[repeating-linear-gradient(90deg,#A83E32_0_8px,transparent_8px_16px)]" />
            <AgentCard title="Budget Agent" desc="Reads your budget and dates, sets constraints for everything downstream." />
            <AgentCard title="Search Agent" desc="Finds flights and stays that fit, ranked by fit rather than price alone." />
            <AgentCard title="Ranking Agent" desc="Assembles the shortlist into a single boarding-pass itinerary." />
          </div>
        </div>
      </section>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <label className="block font-mono text-[9px] tracking-wider text-paper/55 uppercase mb-1">{label}</label>
      <span className="font-mono text-[13px] text-paper">{value}</span>
    </div>
  )
}

function AgentCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="relative text-center px-4">
      <div className="w-3 h-3 rounded-full bg-route mx-auto mt-7 mb-4.5 relative z-10 shadow-[0_0_0_6px_#F6F4EF]" />
      <h3 className="font-mono text-xs tracking-wide uppercase text-ink mb-2">{title}</h3>
      <p className="text-[13.5px] text-muted leading-relaxed">{desc}</p>
    </div>
  )
}
