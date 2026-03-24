import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { LogoWithMatchedBackground } from '@/components/LogoWithMatchedBackground'
import { ChevronLeft, ChevronRight } from 'lucide-react'

/** Green checkmark icon for pipeline completion (corporate-friendly) */
function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 6L9 17l-5-5" />
    </svg>
  )
}

/** Speedy scroll to element (faster than native smooth scroll) */
function scrollToOverview() {
  const el = document.getElementById('overview-steps')
  if (!el) return
  const start = window.scrollY
  const target = el.getBoundingClientRect().top + start
  const distance = target - start
  const duration = 450
  let startTime: number | null = null
  function easeOutCubic(t: number) {
    return 1 - Math.pow(1 - t, 3)
  }
  function step(timestamp: number) {
    if (!startTime) startTime = timestamp
    const elapsed = timestamp - startTime
    const progress = Math.min(elapsed / duration, 1)
    window.scrollTo(0, start + distance * easeOutCubic(progress))
    if (progress < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

/** Overview step card data */
const OVERVIEW_STEPS = [
  {
    title: 'Load & Clean Data',
    description: 'Exact rules and keys align the highest-confidence transactions first.',
    icon: 'table',
    iconFile: '/icons/1_file-spreadsheet.png',
  },
  {
    title: 'Deterministic Matching',
    description: 'Exact rules and keys align the highest-confidence transactions first.',
    icon: 'binary',
    iconFile: '/icons/2_magnifying-glass-binary.png',
  },
  {
    title: 'Probabilistic Matching',
    description: 'Fuzzy logic and scoring surface near-matches and partial overlaps.',
    icon: 'sort',
    iconFile: '/icons/3_settings-sliders.png',
  },
  {
    title: 'AI Matching',
    description: 'Machine learning and patterns handle the long tail and edge cases.',
    icon: 'star',
    iconFile: '/icons/4_artificial-intelligence.png',
  },
  {
    title: 'Review & Override',
    description: 'Row-level review with accept, override, or mark unmatched—you stay in control.',
    icon: 'clipboard',
    iconFile: '/icons/5_clipboard-check.png',
  },
  {
    title: 'Audit-Ready Export',
    description: 'Complete reconciliation package: datasets, logs, and optional executive summary PDF.',
    icon: 'document',
    iconFile: '/icons/6_file-export.png',
  },
]

/** Icon components for overview steps (white on black cards) */
function StepIcon({ type, iconFile, className }: { type: string; iconFile?: string | null; className?: string }) {
  if (iconFile) {
    return <img src={iconFile} alt="" aria-hidden className={`w-8 h-8 object-contain ${className ?? ''}`} />
  }
  const base = 'stroke-white stroke-[1.5]'
  switch (type) {
    case 'table':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
        </svg>
      )
    case 'binary':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <text x="6" y="10" fontSize="7" fontWeight="600" fill="white" fontFamily="ui-monospace, monospace">01</text>
          <text x="6" y="18" fontSize="7" fontWeight="600" fill="white" fontFamily="ui-monospace, monospace">10</text>
        </svg>
      )
    case 'sort':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M7 15l3-3 3 3M7 9l3 3 3-3" />
          <line x1="12" y1="3" x2="12" y2="21" />
        </svg>
      )
    case 'star':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9" />
        </svg>
      )
    case 'clipboard':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
          <rect x="8" y="2" width="8" height="4" rx="1" />
          <path d="M9 14l2 2 4-4" />
        </svg>
      )
    case 'document':
      return (
        <svg className={`${base} ${className}`} width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <path d="M9 15l2 2 4-4" />
        </svg>
      )
    default:
      return null
  }
}

/** Demo data for the Matching card (illustrates pipeline output per screenshot) */
const DEMO_PIPELINE = [
  { label: 'Deterministic Matching', amount: 261245, records: 100 },
  { label: 'Probabilistic Matching', amount: 52890, records: 15 },
  { label: 'AI Matching', amount: 32908, records: 5 },
] as const
const DEMO_TOTAL_RECORDS = 120
const DEMO_TOTAL_AMOUNT = 347043


export function Landing() {
  const [activeStep, setActiveStep] = useState(0)

  return (
    <div
      className="min-h-screen font-sans text-foreground relative flex flex-col"
      style={{ background: 'var(--primary)' }}
    >
      {/* LAYER 1: Red rectangle — continuous base for entire page (both sections).
          Red shows through in rounded corners of charcoal (top) and white (bottom). */}

      {/* Header — fixed above both sections */}
      <header className="fixed top-0 left-0 right-0 z-30 flex items-center justify-end px-6 lg:px-10 py-4 bg-[#333333]/95 backdrop-blur-md">
        <nav className="flex items-center gap-6">
          <button
            type="button"
            className="text-sm font-medium text-white/70 hover:text-white transition-colors"
          >
            Documentation
          </button>
          <a
            href="#faq"
            className="text-sm font-medium text-white/70 hover:text-white transition-colors"
          >
            FAQ
          </a>
          <Button asChild size="default">
            <Link to="/load-files">Get Started</Link>
          </Button>
        </nav>
      </header>

      {/* Layer 2: Top section — Charcoal fills section, square top, rounded bottom (red shows in bottom corners) */}
      <div
        className="relative z-10 h-screen min-h-[600px] overflow-hidden bg-[#333333] flex flex-col rounded-b-[clamp(40px,5vw,80px)]"
      >
        <main className="flex-1 pt-[clamp(4.5rem,8vh,5rem)] pb-4 px-6 lg:px-10 overflow-y-auto">
          <div className="max-w-7xl mx-auto flex flex-col lg:flex-row gap-12 lg:gap-16 items-start">
            {/* Left: Branding (CUSTOMER_UI_SPEC) */}
            <div className="flex-1 max-w-xl">
              <LogoWithMatchedBackground alt="ReconAI" background="charcoal" className="h-[clamp(160px,22vh,280px)] w-auto" />
              <div className="mt-[min(40px,3.5vh)] space-y-4">
                <h1 className="text-[2rem] lg:text-[2.5rem] font-bold tracking-tight text-foreground leading-[1.15]">
                  Reconcile your GL in minutes.<br />
                  Get audit-ready outputs.
                </h1>
                <p className="text-base text-muted-foreground leading-relaxed mb-3">
                  Built for busy accounting professionals.
                </p>
                <p className="text-[0.9375rem] text-muted-foreground/90 leading-[1.6] mb-5">
                  Matches begin with the strongest signal and progressively expand through
                  deterministic, probabilistic, and AI-assisted matching. You maintain full
                  control with row-level review and override capabilities. The result is a
                  complete reconciliation with an audit-ready export package.
                </p>
                <div className="flex justify-center">
                  <Button
                    size="default"
                    className="animate-bounce-subtle"
                    onClick={scrollToOverview}
                  >
                    Learn More
                  </Button>
                </div>
              </div>
            </div>

            {/* Right: Matching dashboard card (second screenshot style) */}
          <div id="matching-card" className="w-full lg:flex-1 lg:flex lg:justify-center">
            <div className="bg-white rounded-2xl shadow-[0_2px_8px_rgba(0,0,0,0.08)] p-6 text-[#1a1a1a]">
              <h2 className="text-[1.5rem] font-bold tracking-tight">
                Matching
              </h2>
              <p className="text-[0.875rem] text-[#6b7280] mt-1 mb-6 leading-relaxed">
                Reconciliation pipeline: deterministic, probabilistic, and AI matching.
              </p>

              {/* Pipeline Status */}
              <div className="mb-6">
                <h3 className="text-[1.125rem] font-semibold mb-2">
                  Pipeline Status
                </h3>
                <p className="text-[0.875rem] text-[#6b7280] mb-4 leading-relaxed">
                  Reconciliation runs through deterministic, probabilistic, and AI matching.
                </p>
                <div className="divide-y divide-[#e5e7eb]">
                  {DEMO_PIPELINE.map(({ label, amount, records }) => (
                    <div
                      key={label}
                      className="flex items-center justify-between py-4 first:pt-0 last:pb-0"
                    >
                      <div className="flex items-center gap-3">
                        <CheckIcon className="text-emerald-500 shrink-0" />
                        <span className="text-[0.9375rem] font-medium text-[#374151]">
                          {label}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-[0.9375rem] font-medium text-[#374151] tabular-nums">
                          $
                          {amount.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })}
                        </span>
                        <span className="text-[0.75rem] text-[#9ca3af] ml-2">
                          {records} records
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Run Status */}
              <div>
                <h3 className="text-[1.125rem] font-semibold mb-2">Run Status</h3>
                <p className="text-[0.875rem] text-[#6b7280] mb-4 leading-relaxed">
                  Current run progress and summary
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Current Status</p>
                    <p className="text-[0.9375rem] font-semibold mt-0.5">Complete</p>
                  </div>
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Total records processed</p>
                    <p className="text-[0.9375rem] font-semibold tabular-nums mt-0.5">
                      {DEMO_TOTAL_RECORDS.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Total amount processed</p>
                    <p className="text-[0.9375rem] font-semibold tabular-nums mt-0.5">
                      $
                      {DEMO_TOTAL_AMOUNT.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        </main>
      </div>

      {/* Layer 3: Bottom section — White rounded rect fills section (red shows in corners) */}
      <section
        id="overview-steps"
        className="relative z-10 h-screen min-h-[600px] overflow-hidden flex flex-col scroll-mt-20"
      >
        <div
          className="bg-white rounded-[clamp(40px,5vw,80px)] pt-[clamp(5rem,9vh,7rem)] pb-[clamp(1rem,2vh,2rem)] px-8 lg:px-12 flex-1 min-h-0 flex flex-col w-full"
        >
              <h2 className="text-[clamp(1.75rem,3.5vw,3.25rem)] font-bold text-[#1a1a1a] text-center mb-[clamp(1rem,2vh,1.5rem)]">
                Your Reconciliation Pipeline
              </h2>

              {/* iPod-style carousel — card size and spacing scale with viewport */}
              <div className="relative flex items-center justify-center flex-1 min-h-0 overflow-hidden">
                {OVERVIEW_STEPS.map((step, idx) => {
                  const offset = idx - activeStep
                  const isActive = offset === 0
                  const absOffset = Math.abs(offset)
                  const scale = isActive ? 1 : Math.max(0.5, 1 - absOffset * 0.15)
                  const blur = isActive ? 0 : Math.min(8, absOffset * 2)
                  const opacity = isActive ? 1 : Math.max(0.3, 1 - absOffset * 0.2)

                  return (
                    <div
                      key={idx}
                      className="absolute transition-all duration-300 ease-out"
                      style={{
                        transform: `translateX(calc(${offset} * clamp(110px, 11vw, 180px))) scale(${scale})`,
                        filter: blur ? `blur(${blur}px)` : 'none',
                        opacity,
                        zIndex: isActive ? 10 : 5 - absOffset,
                        pointerEvents: isActive ? 'auto' : 'none',
                      }}
                    >
                      <div
                        className="bg-[#333333] rounded-2xl shadow-xl text-white flex flex-col"
                        style={{
                          width: 'clamp(220px, 26vw, 420px)',
                          height: 'clamp(220px, min(26vw, 42vh), 420px)',
                          padding: 'clamp(1.25rem, 2.5vw, 2.5rem)',
                        }}
                      >
                        <div className="flex items-center justify-center w-[clamp(32px,3vw,42px)] h-[clamp(32px,3vw,42px)] mb-[clamp(0.75rem,1.5vh,1.5rem)] [&_svg]:text-white shrink-0">
                          <StepIcon type={step.icon} iconFile={step.iconFile} className="scale-[1.75]" />
                        </div>
                        <h3 className="font-bold mb-2 text-[clamp(1rem,1.6vw,1.5rem)]">{step.title}</h3>
                        <p className="text-white/80 leading-relaxed text-[clamp(0.8rem,1.1vw,1rem)]">{step.description}</p>
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Dots + navigation controls: [Back] [dots] [Next/Get Started] */}
              <div className="flex items-center justify-center gap-6 mt-8">
                {activeStep >= 1 && (
                  <button
                    type="button"
                    onClick={() => setActiveStep((s) => s - 1)}
                    className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary/20 hover:bg-primary/30 text-primary text-sm font-medium transition-colors"
                    aria-label="Previous step"
                  >
                    <ChevronLeft className="size-4" />
                    Back
                  </button>
                )}
                <div className="flex gap-2">
                  {OVERVIEW_STEPS.map((_, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => setActiveStep(idx)}
                      className={`size-2 rounded-full transition-colors ${
                        idx === activeStep ? 'bg-primary' : 'bg-gray-300 hover:bg-gray-400'
                      }`}
                      aria-label={`Go to step ${idx + 1}`}
                    />
                  ))}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {activeStep <= 4 ? (
                    <button
                      type="button"
                      onClick={() => setActiveStep((s) => s + 1)}
                      className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium transition-colors"
                      aria-label="Next step"
                    >
                      Next
                      <ChevronRight className="size-4" />
                    </button>
                  ) : (
                    <Button asChild size="default">
                      <Link to="/load-files" className="flex items-center gap-1">
                        Get Started
                        <ChevronRight className="size-4" />
                      </Link>
                    </Button>
                  )}
                </div>
              </div>
            </div>
        </section>
    </div>
  )
}
