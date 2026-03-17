import { useMutation } from '@tanstack/react-query'
import { useNavigate, Link } from 'react-router-dom'
import { startSession } from '@/api/endpoints'
import HealthIndicator from '@/components/HealthIndicator'
import ErrorDisplay from '@/components/ErrorDisplay'
import ReconAILogo from '@/components/ReconAILogo'

/** Green checkmark icon for pipeline completion (matches CUSTOMER_UI_SPEC accent restraint) */
function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 6L9 17l-5-5" />
    </svg>
  )
}

/** Demo data for the Matching card on landing (illustrates pipeline output) */
const DEMO_PIPELINE = [
  { label: 'Deterministic Matching', amount: 261245, records: 100 },
  { label: 'Probabilistic Matching', amount: 52890, records: 15 },
  { label: 'AI Matching', amount: 32908, records: 5 },
] as const
const DEMO_TOTAL_RECORDS = 120
const DEMO_TOTAL_AMOUNT = 347043

function handleResetSession() {
  localStorage.removeItem('recon_sessions')
  window.location.href = '/'
}

export default function LandingPage() {
  const navigate = useNavigate()

  const startMutation = useMutation({
    mutationFn: startSession,
    onSuccess: (data) => {
      const stored = JSON.parse(localStorage.getItem('recon_sessions') ?? '[]') as string[]
      if (!stored.includes(data.session_id)) {
        stored.unshift(data.session_id)
        localStorage.setItem('recon_sessions', JSON.stringify(stored))
      }
      navigate(`/sessions/${data.session_id}`)
    },
  })

  return (
    <div className="min-h-screen bg-void font-sans text-white">
      {/* ── Header ── */}
      <header className="fixed top-0 left-0 right-0 z-10 flex items-center justify-between px-6 lg:px-10 py-4 bg-void/95 backdrop-blur-md border-b border-void-border">
        <ReconAILogo variant="light" size="md" />
        <nav className="flex items-center gap-6">
          <Link to="/" className="text-sm font-medium text-white/70 hover:text-white transition-colors">
            Home
          </Link>
          <button
            type="button"
            onClick={handleResetSession}
            className="text-sm font-medium text-white/70 hover:text-white transition-colors"
          >
            Reset Session
          </button>
          <a href="#faq" className="text-sm font-medium text-white/70 hover:text-white transition-colors">
            FAQ
          </a>
          <HealthIndicator />
          <button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending}
            className="btn-primary"
          >
            {startMutation.isPending ? 'Starting…' : 'Get Started'}
          </button>
        </nav>
      </header>

      {/* ── Main content: split layout ── */}
      <main className="pt-24 pb-16 px-6 lg:px-10">
        <div className="max-w-7xl mx-auto flex flex-col lg:flex-row gap-12 lg:gap-16 items-start">
          {/* Left: Branding (CUSTOMER_UI_SPEC) */}
          <div className="flex-1 max-w-xl">
            <ReconAILogo variant="light" size="lg" className="mb-6" />
            <p className="text-bdo-red text-lg font-semibold mb-2 tracking-tight">
              Trust at Scale
            </p>
            <h1 className="text-[2rem] lg:text-[2.5rem] font-bold tracking-tight text-white leading-[1.15] mb-4">
              Reconcile your GL in minutes with audit-ready outputs.
            </h1>
            <p className="text-base text-white/65 leading-relaxed mb-6">
              Built for busy accounting professionals.
            </p>
            <p className="text-[0.9375rem] text-white/55 leading-[1.6] mb-8">
              Matches begin with the strongest signal and progressively expand through deterministic, probabilistic, and AI-assisted matching. You maintain full control with row-level review and override capabilities. The result is a complete reconciliation with an audit-ready export package.
            </p>
            <button
              type="button"
              onClick={() => document.getElementById('matching-card')?.scrollIntoView({ behavior: 'smooth' })}
              className="btn-secondary"
            >
              Learn More
            </button>
          </div>

          {/* Right: Matching dashboard card (screenshot 2 style) */}
          <div id="matching-card" className="w-full lg:w-[420px] shrink-0">
            <div className="bg-white rounded-2xl shadow-card p-6 text-void">
              <h2 className="text-[1.5rem] font-bold text-[#1a1a1a] tracking-tight">
                Matching
              </h2>
              <p className="text-[0.875rem] text-[#6b7280] mt-1 mb-6 leading-relaxed">
                Reconciliation pipeline: deterministic, probabilistic, and AI matching.
              </p>

              {/* Pipeline Status */}
              <div className="mb-6">
                <h3 className="text-[1.125rem] font-semibold text-[#1a1a1a] mb-2">
                  Pipeline Status
                </h3>
                <p className="text-[0.875rem] text-[#6b7280] mb-4 leading-relaxed">
                  Reconciliation runs through deterministic, probabilistic, and AI matching.
                </p>
                <div className="divide-y divide-[#e5e7eb]">
                  {DEMO_PIPELINE.map(({ label, amount, records }) => (
                    <div key={label} className="flex items-center justify-between py-4 first:pt-0 last:pb-0">
                      <div className="flex items-center gap-3">
                        <CheckIcon className="text-emerald-500 shrink-0" />
                        <span className="text-[0.9375rem] font-medium text-[#374151]">{label}</span>
                      </div>
                      <div className="text-right">
                        <span className="text-[0.9375rem] font-medium text-[#374151] tabular-nums">
                          ${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <span className="text-[0.75rem] text-[#9ca3af] ml-2">{records} records</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Run Status */}
              <div>
                <h3 className="text-[1.125rem] font-semibold text-[#1a1a1a] mb-2">
                  Run Status
                </h3>
                <p className="text-[0.875rem] text-[#6b7280] mb-4 leading-relaxed">
                  Current run progress and summary
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Current Status</p>
                    <p className="text-[0.9375rem] font-semibold text-[#1a1a1a] mt-0.5">Complete</p>
                  </div>
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Total records processed</p>
                    <p className="text-[0.9375rem] font-semibold text-[#1a1a1a] tabular-nums mt-0.5">
                      {DEMO_TOTAL_RECORDS.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <p className="text-[0.875rem] text-[#6b7280]">Total amount processed</p>
                    <p className="text-[0.9375rem] font-semibold text-[#1a1a1a] tabular-nums mt-0.5">
                      ${DEMO_TOTAL_AMOUNT.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* FAQ (anchor for #faq nav link) */}
        <section id="faq" className="max-w-3xl mx-auto mt-20 pt-12 border-t border-void-border">
          <h2 className="text-lg font-semibold text-white mb-4">Frequently Asked Questions</h2>
          <p className="text-sm text-white/50">
            For detailed documentation and support, contact your administrator.
          </p>
        </section>
      </main>

      {/* Error toast */}
      {startMutation.error && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-20">
          <ErrorDisplay error={startMutation.error} />
        </div>
      )}

      {/* Subtle curved accent (bottom right) */}
      <div
        className="fixed bottom-0 right-0 w-80 h-80 pointer-events-none opacity-20"
        style={{
          background: 'radial-gradient(circle at 100% 100%, #CC2529 0%, transparent 70%)',
        }}
        aria-hidden
      />
    </div>
  )
}
