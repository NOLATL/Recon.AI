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

function FinalizedPanel() {
  return (
    <div className="bg-green-50 border border-green-200 rounded-lg p-6 text-center">
      <div className="text-3xl mb-2">✓</div>
      <h3 className="text-lg font-semibold text-green-800">Reconciliation Finalized</h3>
      <p className="text-sm text-green-700 mt-1">
        All files have been exported. This session is complete.
      </p>
    </div>
  )
}

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
      return <ConsolidateStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'final_consolidated':
      return <ExportStep sessionId={sessionId} onSuccess={onSuccess} />
    case 'finalized':
      return <FinalizedPanel />
    default:
      return null
  }
}

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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Sessions
          </Link>
          <span className="text-gray-300">|</span>
          <span className="font-mono text-sm text-gray-700">{sessionId}</span>
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setShowSnapshots((v) => !v)}
            className="text-sm text-gray-600 hover:text-gray-900 border border-gray-200 px-3 py-1.5 rounded-md transition-colors"
          >
            {showSnapshots ? 'Hide Snapshots' : 'Snapshots'}
          </button>
          <HealthIndicator />
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-8 flex gap-6">
        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Status header */}
          <div className="bg-white border border-gray-200 rounded-lg p-5 mb-6">
            {statusQuery.isLoading && (
              <p className="text-sm text-gray-500">Loading status…</p>
            )}
            {statusQuery.error && (
              <div>
                <ErrorDisplay error={statusQuery.error} />
                <button
                  onClick={refetchStatus}
                  className="mt-2 text-sm text-blue-600 hover:text-blue-700"
                >
                  Refresh status
                </button>
              </div>
            )}
            {statusQuery.data && (
              <>
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">Current State</span>
                      {statusQuery.data.is_review_phase && (
                        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
                          Review Phase
                        </span>
                      )}
                    </div>
                    <p className="text-lg font-mono font-semibold text-blue-700 mt-0.5">
                      {statusQuery.data.current_state}
                    </p>
                  </div>
                  <div className="text-right text-sm text-gray-500">
                    <div>{statusQuery.data.snapshot_count} snapshots</div>
                    <button
                      onClick={refetchStatus}
                      className="text-blue-600 hover:text-blue-700 text-xs mt-1"
                    >
                      Refresh
                    </button>
                  </div>
                </div>
                <MatchingSummaryBadges summary={statusQuery.data.matching_summary} />
              </>
            )}
          </div>

          {/* Timeline */}
          {statusQuery.data && (
            <div className="bg-white border border-gray-200 rounded-lg p-5 mb-6">
              <h2 className="text-sm font-medium text-gray-700 mb-4">State Machine</h2>
              <StateMachineTimeline currentState={statusQuery.data.current_state} />
            </div>
          )}

          {/* Active step */}
          {statusQuery.data && (
            <StepPanel
              state={statusQuery.data.current_state}
              sessionId={sessionId}
              onSuccess={refetchStatus}
            />
          )}
        </div>

        {/* Snapshots sidebar */}
        {showSnapshots && (
          <aside className="w-80 flex-shrink-0">
            <SnapshotPanel sessionId={sessionId} />
          </aside>
        )}
      </div>
    </div>
  )
}
