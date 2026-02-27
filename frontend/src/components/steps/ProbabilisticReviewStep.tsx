import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { confirmProbabilisticReview, getSessionStatus } from '@/api/endpoints'
import type { ProbabilisticReviewResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

type Decision = 'accepted' | 'rejected' | null

function ReviewResult({ data }: { data: ProbabilisticReviewResponse }) {
  return (
    <div className="mt-5 space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-green-50 border border-green-200 rounded-md p-4 text-center">
          <p className="text-xs text-green-600">Accepted</p>
          <p className="text-2xl font-bold text-green-800">{data.accepted_count}</p>
        </div>
        <div className="bg-red-50 border border-red-200 rounded-md p-4 text-center">
          <p className="text-xs text-red-600">Rejected</p>
          <p className="text-2xl font-bold text-red-800">{data.rejected_count}</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-md p-4 text-center">
          <p className="text-xs text-gray-500">State</p>
          <p className="text-sm font-semibold text-gray-900 mt-1">{data.state}</p>
        </div>
      </div>
    </div>
  )
}

export default function ProbabilisticReviewStep({ sessionId, onSuccess }: Props) {
  // We need the current matches — fetch the status to see if we can get them,
  // but the probabilistic matches are stored server-side. We'll construct decisions
  // by letting the user enter match IDs or we load them from a cached prior result.
  // Since the API doesn't have a "get current prob matches" GET endpoint,
  // we store the matches in local state after running probabilistic.
  // The step panel is shown when state === probabilistic_complete.
  // We use a local query to re-run the status and get the matching_summary,
  // but we need the actual matches. We'll use a simple approach:
  // Show a form-based UI where user sees "N matches to review" and bulk actions.

  const statusQuery = useQuery({
    queryKey: ['status', sessionId],
    queryFn: () => getSessionStatus(sessionId),
  })

  // decisions keyed by match_id
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  // Since we don't have a GET endpoint for probabilistic matches from this state,
  // we store them in sessionStorage from the ProbabilisticStep result.
  // Check sessionStorage for cached matches.
  const cachedMatchesRaw = sessionStorage.getItem(`prob_matches_${sessionId}`)
  const cachedMatches: Array<{
    match_id: string
    final_similarity: number
    grouping_type: string
    record_ids_A: string[]
    record_ids_B: string[]
    user_status: string
  }> = cachedMatchesRaw ? JSON.parse(cachedMatchesRaw) : []

  const setDecision = (matchId: string, d: Decision) => {
    setDecisions((prev) => ({ ...prev, [matchId]: d }))
  }

  const acceptAll = () => {
    const next: Record<string, Decision> = {}
    cachedMatches.forEach((m) => { next[m.match_id] = 'accepted' })
    setDecisions(next)
  }

  const rejectAll = () => {
    const next: Record<string, Decision> = {}
    cachedMatches.forEach((m) => { next[m.match_id] = 'rejected' })
    setDecisions(next)
  }

  const clearAll = () => setDecisions({})

  const mutation = useMutation({
    mutationFn: () => {
      const decided = Object.entries(decisions)
        .filter(([, d]) => d !== null)
        .map(([match_id, decision]) => ({ match_id, decision: decision! }))
      return confirmProbabilisticReview(sessionId, { decisions: decided })
    },
    onSuccess,
  })

  const probCount = statusQuery.data?.matching_summary['probabilistic'] ?? cachedMatches.length
  const decidedCount = Object.values(decisions).filter(Boolean).length

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Probabilistic Review</h2>
      <p className="text-sm text-gray-500 mb-2">
        Accept or reject each probabilistic match. Accepted matches are promoted to the final
        bucket; rejected matches are returned to the residual pool.
      </p>
      <div className="bg-amber-50 border border-amber-100 rounded-md p-3 text-sm text-amber-700 mb-5">
        {probCount} probabilistic matches pending review. You may submit a partial decision — undecided
        matches remain as "pending."
      </div>

      {/* Bulk actions */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={acceptAll}
          className="text-xs bg-green-100 hover:bg-green-200 text-green-700 px-3 py-1.5 rounded-md transition-colors"
        >
          Accept All
        </button>
        <button
          onClick={rejectAll}
          className="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-3 py-1.5 rounded-md transition-colors"
        >
          Reject All
        </button>
        <button
          onClick={clearAll}
          className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-md transition-colors"
        >
          Clear All
        </button>
        <span className="text-xs text-gray-400 self-center ml-2">
          {decidedCount} of {cachedMatches.length} decided
        </span>
      </div>

      {/* Match rows */}
      {cachedMatches.length > 0 ? (
        <div className="border border-gray-200 rounded-md overflow-hidden mb-5">
          <table className="w-full text-xs">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Match ID</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Grouping</th>
                <th className="text-right py-2 px-3 font-medium text-gray-600">Similarity</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">GL IDs</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Sub IDs</th>
                <th className="text-center py-2 px-3 font-medium text-gray-600">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {cachedMatches.map((m) => {
                const d = decisions[m.match_id] ?? null
                return (
                  <tr key={m.match_id} className={d === 'accepted' ? 'bg-green-50' : d === 'rejected' ? 'bg-red-50' : ''}>
                    <td className="py-2 px-3 font-mono text-gray-700">{m.match_id}</td>
                    <td className="py-2 px-3 text-gray-600">{m.grouping_type}</td>
                    <td className="py-2 px-3 text-right font-medium">
                      {(m.final_similarity * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 px-3 font-mono text-gray-500 max-w-[80px] truncate">
                      {m.record_ids_A.join(', ')}
                    </td>
                    <td className="py-2 px-3 font-mono text-gray-500 max-w-[80px] truncate">
                      {m.record_ids_B.join(', ')}
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex gap-1 justify-center">
                        <button
                          onClick={() => setDecision(m.match_id, 'accepted')}
                          className={[
                            'px-2 py-1 rounded text-[10px] font-medium transition-colors',
                            d === 'accepted'
                              ? 'bg-green-600 text-white'
                              : 'bg-green-100 text-green-700 hover:bg-green-200',
                          ].join(' ')}
                        >
                          Accept
                        </button>
                        <button
                          onClick={() => setDecision(m.match_id, 'rejected')}
                          className={[
                            'px-2 py-1 rounded text-[10px] font-medium transition-colors',
                            d === 'rejected'
                              ? 'bg-red-600 text-white'
                              : 'bg-red-100 text-red-700 hover:bg-red-200',
                          ].join(' ')}
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-md p-4 text-sm text-gray-500 mb-5">
          Match details not available in this view (run probabilistic matching first in this session).
          You can still submit a bulk decision using the buttons above, or submit with no decisions to
          advance the state (all matches remain "pending").
        </div>
      )}

      {mutation.error && (
        <div className="mb-4">
          <ErrorDisplay error={mutation.error} onRefresh={onSuccess} />
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {mutation.isPending ? 'Submitting…' : 'Submit Decisions'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
