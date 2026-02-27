import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { confirmAIReview, getSessionStatus } from '@/api/endpoints'
import type { AIReviewResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import { useQuery } from '@tanstack/react-query'

interface Props {
  sessionId: string
  onSuccess: () => void
}

type Decision = 'accepted' | 'rejected' | null

function ReviewResult({ data }: { data: AIReviewResponse }) {
  return (
    <div className="mt-5 space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-green-50 border border-green-200 rounded-md p-4 text-center">
          <p className="text-xs text-green-600">Accepted → Final</p>
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

export default function AIReviewStep({ sessionId, onSuccess }: Props) {
  const statusQuery = useQuery({
    queryKey: ['status', sessionId],
    queryFn: () => getSessionStatus(sessionId),
  })

  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  const cachedRaw = sessionStorage.getItem(`ai_suggestions_${sessionId}`)
  const cachedSuggestions: Array<{
    match_id: string
    ai_confidence_score: number
    grouping_type: string
    materiality: number
    record_ids_A: string[]
    record_ids_B: string[]
    reasoning_narrative: string
    user_status: string
  }> = cachedRaw ? JSON.parse(cachedRaw) : []

  const setDecision = (matchId: string, d: Decision) => {
    setDecisions((prev) => ({ ...prev, [matchId]: d }))
  }

  const acceptAll = () => {
    const next: Record<string, Decision> = {}
    cachedSuggestions.forEach((m) => { next[m.match_id] = 'accepted' })
    setDecisions(next)
  }

  const rejectAll = () => {
    const next: Record<string, Decision> = {}
    cachedSuggestions.forEach((m) => { next[m.match_id] = 'rejected' })
    setDecisions(next)
  }

  const clearAll = () => setDecisions({})

  const mutation = useMutation({
    mutationFn: () => {
      const decided = Object.entries(decisions)
        .filter(([, d]) => d !== null)
        .map(([match_id, decision]) => ({ match_id, decision: decision! }))
      return confirmAIReview(sessionId, { decisions: decided })
    },
    onSuccess,
  })

  const aiCount = statusQuery.data?.matching_summary['ai_suggested'] ?? cachedSuggestions.length
  const decidedCount = Object.values(decisions).filter(Boolean).length

  const [expandedNarrative, setExpandedNarrative] = useState<string | null>(null)

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">AI Review</h2>
      <p className="text-sm text-gray-500 mb-2">
        Accept or reject each AI suggestion. Accepted suggestions are moved to the final bucket;
        rejected suggestions are returned to the residual pool.
      </p>
      <div className="bg-purple-50 border border-purple-100 rounded-md p-3 text-sm text-purple-800 mb-5">
        {aiCount} AI suggestions pending review.
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
          {decidedCount} of {cachedSuggestions.length} decided
        </span>
      </div>

      {/* Suggestion rows */}
      {cachedSuggestions.length > 0 ? (
        <div className="border border-gray-200 rounded-md overflow-hidden mb-5">
          <table className="w-full text-xs">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Match ID</th>
                <th className="text-right py-2 px-3 font-medium text-gray-600">Confidence</th>
                <th className="text-right py-2 px-3 font-medium text-gray-600">Materiality</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">GL IDs</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Sub IDs</th>
                <th className="text-left py-2 px-3 font-medium text-gray-600">Reasoning</th>
                <th className="text-center py-2 px-3 font-medium text-gray-600">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {cachedSuggestions.map((m) => {
                const d = decisions[m.match_id] ?? null
                const isExpanded = expandedNarrative === m.match_id
                return (
                  <tr
                    key={m.match_id}
                    className={d === 'accepted' ? 'bg-green-50' : d === 'rejected' ? 'bg-red-50' : ''}
                  >
                    <td className="py-2 px-3 font-mono text-gray-700">{m.match_id}</td>
                    <td className="py-2 px-3 text-right font-medium">
                      <span
                        className={
                          m.ai_confidence_score >= 0.8
                            ? 'text-green-600'
                            : m.ai_confidence_score >= 0.6
                              ? 'text-amber-600'
                              : 'text-red-500'
                        }
                      >
                        {(m.ai_confidence_score * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right text-gray-600">
                      {m.materiality.toFixed(2)}
                    </td>
                    <td className="py-2 px-3 font-mono text-gray-500 max-w-[80px] truncate">
                      {m.record_ids_A.join(', ')}
                    </td>
                    <td className="py-2 px-3 font-mono text-gray-500 max-w-[80px] truncate">
                      {m.record_ids_B.join(', ')}
                    </td>
                    <td className="py-2 px-3 max-w-[200px]">
                      <p className="text-gray-600 line-clamp-2">
                        {isExpanded ? m.reasoning_narrative : m.reasoning_narrative.slice(0, 80)}
                        {m.reasoning_narrative.length > 80 && !isExpanded && '…'}
                      </p>
                      {m.reasoning_narrative.length > 80 && (
                        <button
                          onClick={() => setExpandedNarrative(isExpanded ? null : m.match_id)}
                          className="text-blue-500 hover:text-blue-700 text-[10px]"
                        >
                          {isExpanded ? 'Collapse' : 'Expand'}
                        </button>
                      )}
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
          AI suggestion details not available (run the AI step in this session). You may still submit
          with no decisions to advance the state.
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
        className="bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {mutation.isPending ? 'Submitting…' : 'Submit AI Review Decisions'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
