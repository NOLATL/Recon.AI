import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getSessionStatus } from '@/api/endpoints'
import type { ReconciliationState } from '@/schemas'
import HealthIndicator from '@/components/HealthIndicator'
import StateMachineTimeline from '@/components/StateMachineTimeline'
import ErrorDisplay from '@/components/ErrorDisplay'
import SnapshotPanel from '@/components/SnapshotPanel'
import MatchingSummaryBadges from '@/components/MatchingSummaryBadges'
import ReconAILogo from '@/components/ReconAILogo'

// Step components
import UploadStep from '@/components/steps/UploadStep'
import ProfileStep from '@/components/steps/ProfileStep'
import PreprocessStep from '@/components/steps/PreprocessStep'
import DeterministicStep from '@/components/steps/DeterministicStep'
import DeterministicReviewStep from '@/components/steps/DeterministicReviewStep'
import ProbabilisticStep from '@/components/steps/ProbabilisticStep'
import ProbabilisticReviewStep from '@/components/steps/ProbabilisticReviewStep'
import AIStep from '@/components/steps/AIStep'
import AIReviewStep from '@/components/steps/AIReviewStep'
import ConsolidateStep from '@/components/steps/ConsolidateStep'
import ExportStep from '@/components/steps/ExportStep'

// ── Nav section mapping ────────────────────────────────────────────────────────

type NavSection = 'load_files' | 'matching' | 'matched_analysis' | 'unmatched_analysis' | 'export'

function getNavSection(state: ReconciliationState): NavSection {
  if (state === 'initialized' || state === 'files_loaded') return 'load_files'
  if (
    state === 'profiled' ||
    state === 'preprocessed' ||
    state === 'deterministic_complete' ||
    state === 'deterministic_review_complete' ||
    state === 'probabilistic_complete' ||
    state === 'probabilistic_review_complete' ||
    state === 'ai_suggested' ||
    state === 'ai_review_complete'
  ) return 'matching'
  if (state === 'final_consolidated') return 'matched_analysis'
  if (state === 'finalized') return 'export'
  return 'load_files'
}

// ── SVG icons ─────────────────────────────────────────────────────────────────

const GridIcon = () => (
  <svg viewBox="0 0 16 16" fill="currentColor" width="16" height="16">
    <rect x="1" y="1" width="6" height="6" rx="1" /><rect x="9" y="1" width="6" height="6" rx="1" />
    <rect x="1" y="9" width="6" height="6" rx="1" /><rect x="9" y="9" width="6" height="6" rx="1" />
  </svg>
)
const UploadIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <path d="M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2M8 2v8M5 5l3-3 3 3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const MatchIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <path d="M2 4h5M9 4h5M2 8h3M11 8h3M2 12h7M11 12h3" strokeLinecap="round" />
    <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
  </svg>
)
const BarChartIcon = () => (
  <svg viewBox="0 0 16 16" fill="currentColor" width="16" height="16">
    <rect x="1" y="8" width="3" height="7" rx="0.5" /><rect x="6" y="4" width="3" height="11" rx="0.5" />
    <rect x="11" y="1" width="3" height="14" rx="0.5" />
  </svg>
)
const ResidualIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <rect x="2" y="2" width="12" height="12" rx="2" />
    <path d="M6 8h4M8 6v4" strokeLinecap="round" />
  </svg>
)
const ExportIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <path d="M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2M8 2v8M5 5l3 3 3-3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const ResetIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <path d="M3 8A5 5 0 1013 8M3 8V5M3 8H6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const SnapshotIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="16" height="16">
    <rect x="2" y="3" width="12" height="10" rx="1.5" />
    <path d="M5 7h6M5 10h4" strokeLinecap="round" />
  </svg>
)

// ── Nav item ───────────────────────────────────────────────────────────────────

interface NavItemProps {
  label: string
  icon: React.ReactNode
  section: NavSection
  activeSection: NavSection
  reachedSections: Set<NavSection>
}

function NavItem({ label, icon, section, activeSection, reachedSections }: NavItemProps) {
  const isActive = section === activeSection
  const isReached = reachedSections.has(section)

  return (
    <div
      className={[
        'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors select-none',
        isActive
          ? 'bg-bdo-red-glow text-bdo-red-light font-semibold'
          : isReached
            ? 'text-white/70 hover:text-white/90 hover:bg-void-elevated cursor-default'
            : 'text-white/25 cursor-default',
      ].join(' ')}
    >
      <span className="w-4 h-4 flex-shrink-0">{icon}</span>
      <span>{label}</span>
      {isActive && (
        <span className="ml-auto w-1.5 h-1.5 rounded-full bg-bdo-red flex-shrink-0" />
      )}
    </div>
  )
}

// ── Step panel router ──────────────────────────────────────────────────────────

function StepPanel({
  state,
  sessionId,
  onSuccess,
}: {
  state: ReconciliationState
  sessionId: string
  onSuccess: () => void
}) {
  switch (state) {
    case 'initialized':
      return <UploadStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'files_loaded':
      return <ProfileStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'profiled':
      return <PreprocessStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'preprocessed':
      return <DeterministicStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'deterministic_complete':
      return <DeterministicReviewStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'deterministic_review_complete':
      return <ProbabilisticStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'probabilistic_complete':
      return <ProbabilisticReviewStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'probabilistic_review_complete':
      return <AIStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'ai_suggested':
      return <AIReviewStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'ai_review_complete':
      return <ConsolidateStep sessionId={sessionId} state={state} onSuccess={onSuccess} />
    case 'final_consolidated':
    case 'finalized':
      return (
        <div className="space-y-4">
          <ConsolidateStep sessionId={sessionId} state={state} onSuccess={onSuccess} />
          <ExportStep sessionId={sessionId} state={state} onSuccess={onSuccess} />
        </div>
      )
    default:
      return null
  }
}

// ── Main dashboard ─────────────────────────────────────────────────────────────

export default function SessionDashboard() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [showSnapshots, setShowSnapshots] = useState(false)

  const statusQuery = useQuery({
    queryKey: ['status', sessionId],
    queryFn: () => getSessionStatus(sessionId!),
    refetchInterval: 30_000, // poll every 30s
    enabled: !!sessionId,
  })

  const refetchStatus = () => statusQuery.refetch()

  if (!sessionId) return null

  const currentState = statusQuery.data?.current_state ?? 'initialized'
  const activeSection = getNavSection(currentState)

  const SECTION_ORDER: NavSection[] = ['load_files', 'matching', 'matched_analysis', 'unmatched_analysis', 'export']
  const activeIdx = SECTION_ORDER.indexOf(activeSection)
  const reachedSections = new Set<NavSection>(SECTION_ORDER.slice(0, activeIdx + 1))

  return (
    <div className="min-h-screen bg-void flex font-sans">

      {/* ── Left sidebar ── */}
      <aside className="w-52 bg-void-surface border-r border-void-border flex-shrink-0 flex flex-col px-3 py-5 sticky top-0 h-screen overflow-y-auto">
        {/* Logo */}
        <div className="px-2 mb-8">
          <Link to="/">
            <ReconAILogo variant="light" size="sm" />
          </Link>
        </div>

        {/* Nav items */}
        <nav className="flex-1 space-y-0.5">
          <Link
            to="/"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-white/50 hover:text-white/80 hover:bg-void-elevated transition-colors"
          >
            <span className="w-4 h-4 flex-shrink-0"><GridIcon /></span>
            <span>Landing</span>
          </Link>
          <NavItem label="Load Files"          icon={<UploadIcon />}   section="load_files"          activeSection={activeSection} reachedSections={reachedSections} />
          <NavItem label="Matching"            icon={<MatchIcon />}    section="matching"            activeSection={activeSection} reachedSections={reachedSections} />
          <NavItem label="Matched Analysis"    icon={<BarChartIcon />} section="matched_analysis"    activeSection={activeSection} reachedSections={reachedSections} />
          <NavItem label="Unmatched Analysis"  icon={<ResidualIcon />} section="unmatched_analysis"  activeSection={activeSection} reachedSections={reachedSections} />
          <NavItem label="Export"              icon={<ExportIcon />}   section="export"              activeSection={activeSection} reachedSections={reachedSections} />
        </nav>

        {/* Footer */}
        <div className="mt-4 space-y-0.5 border-t border-void-border pt-4">
          <button
            onClick={() => setShowSnapshots((v) => !v)}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs text-white/40 hover:text-white/70 hover:bg-void-elevated transition-colors"
          >
            <span className="w-4 h-4 flex-shrink-0"><SnapshotIcon /></span>
            {showSnapshots ? 'Hide Snapshots' : 'Snapshots'}
          </button>
          <Link
            to="/"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs text-white/40 hover:text-white/70 hover:bg-void-elevated transition-colors"
          >
            <span className="w-4 h-4 flex-shrink-0"><ResetIcon /></span>
            Reset Session
          </Link>
        </div>

        {/* Health indicator */}
        <div className="mt-3 px-2">
          <HealthIndicator />
        </div>
      </aside>

      {/* ── Main content area ── */}
      <div className="flex-1 min-w-0 flex overflow-hidden">
        <div className="flex-1 min-w-0 px-6 py-7 overflow-y-auto">

          {/* Session ID header */}
          <div className="mb-6">
            <p className="data-label mb-1">Active Session</p>
            <p className="font-mono text-sm text-white/50 truncate">{sessionId}</p>
          </div>

          {/* Status card */}
          <div className="glass-card p-5 mb-4">
            {statusQuery.isLoading && (
              <p className="text-sm text-white/40">Loading status…</p>
            )}
            {statusQuery.error && (
              <div>
                <ErrorDisplay error={statusQuery.error} />
                <button
                  onClick={refetchStatus}
                  className="mt-2 text-xs text-bdo-red hover:text-bdo-red-light transition-colors"
                >
                  Refresh status
                </button>
              </div>
            )}
            {statusQuery.data && (
              <>
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <p className="data-label mb-1.5">Current State</p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-base font-semibold text-white">
                        {statusQuery.data.current_state}
                      </span>
                      {statusQuery.data.is_review_phase && (
                        <span className="status-badge bg-amber-500/15 text-amber-300 border border-amber-500/25">
                          Review Phase
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="data-label mb-1">{statusQuery.data.snapshot_count} snapshots</p>
                    <button
                      onClick={refetchStatus}
                      className="text-[10px] text-bdo-red hover:text-bdo-red-light transition-colors"
                    >
                      Refresh
                    </button>
                  </div>
                </div>
                <MatchingSummaryBadges summary={statusQuery.data.matching_summary} />
              </>
            )}
          </div>

          {/* State machine timeline */}
          {statusQuery.data && (
            <div className="glass-card p-5 mb-5">
              <p className="data-label mb-4">Pipeline Progress</p>
              <StateMachineTimeline currentState={statusQuery.data.current_state} />
            </div>
          )}

          {/* Active step panel */}
          {statusQuery.data && (
            <StepPanel
              state={statusQuery.data.current_state}
              sessionId={sessionId}
              onSuccess={refetchStatus}
            />
          )}
        </div>

        {/* Snapshots panel */}
        {showSnapshots && (
          <aside className="w-80 flex-shrink-0 border-l border-void-border px-4 py-7 overflow-y-auto">
            <SnapshotPanel sessionId={sessionId} />
          </aside>
        )}
      </div>
    </div>
  )
}
