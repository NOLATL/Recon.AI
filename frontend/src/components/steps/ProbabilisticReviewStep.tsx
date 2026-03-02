import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { confirmProbabilisticReview } from '@/api/endpoints'
import type { ProbabilisticResponse, ProbabilisticReviewResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

interface Props {
  sessionId: string
  onSuccess: () => void
}

// ── Shared record grid ──────────────────────────────────────────────────────

function RecordGrid({ records }: { records: Record<string, unknown>[] }) {
  if (records.length === 0) {
    return <p className="text-xs text-gray-400 italic">No record details available.</p>
  }
  const columns = Object.keys(records[0])
  return (
    <div className="overflow-x-auto">
      <table className="text-[11px] w-full">
        <thead>
          <tr className="bg-gray-50">
            {columns.map((col) => (
              <th
                key={col}
                className="py-1.5 px-2 text-left font-medium text-gray-500 whitespace-nowrap border-b border-gray-200"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {records.map((rec, i) => (
            <tr key={i} className="hover:bg-gray-50">
              {columns.map((col) => (
                <td key={col} className="py-1.5 px-2 text-gray-700 whitespace-nowrap">
                  {String(rec[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Result banner after submission ─────────────────────────────────────────

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

// ── Main step ───────────────────────────────────────────────────────────────

export default function ProbabilisticReviewStep({ sessionId, onSuccess }: Props) {
  // Load the full result cached by ProbabilisticStep
  const cachedRaw = sessionStorage.getItem(`prob_result_${sessionId}`)
  const cachedResult: ProbabilisticResponse | null = cachedRaw ? JSON.parse(cachedRaw) : null
  const matches = cachedResult?.matches ?? []

  // Build record lookup maps keyed by ID string
  const glLookup = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>()
    ;(cachedResult?.gl_pool_records ?? []).forEach((rec) => {
      const id = String(rec['gl_id'] ?? '')
      if (id) map.set(id, rec)
    })
    return map
  }, [cachedResult])

  const subLookup = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>()
    ;(cachedResult?.sub_pool_records ?? []).forEach((rec) => {
      const id = String(rec['subledger_id'] ?? '')
      if (id) map.set(id, rec)
    })
    return map
  }, [cachedResult])

  // Checkbox state — default all checked (= accepted)
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    matches.forEach((m) => { init[m.match_id] = true })
    return init
  })

  const [expandedMatches, setExpandedMatches] = useState<Set<string>>(new Set())

  const expandAll = () => setExpandedMatches(new Set(matches.map((m) => m.match_id)))
  const collapseAll = () => setExpandedMatches(new Set())

  const toggleMatch = (matchId: string) =>
    setChecked((prev) => ({ ...prev, [matchId]: !prev[matchId] }))

  const checkAll = () => {
    const next: Record<string, boolean> = {}
    matches.forEach((m) => { next[m.match_id] = true })
    setChecked(next)
  }

  const uncheckAll = () => {
    const next: Record<string, boolean> = {}
    matches.forEach((m) => { next[m.match_id] = false })
    setChecked(next)
  }

  const acceptedCount = matches.filter((m) => checked[m.match_id]).length
  const rejectedCount = matches.length - acceptedCount

  const mutation = useMutation({
    mutationFn: () => {
      const decisions = matches.map((m) => ({
        match_id: m.match_id,
        decision: (checked[m.match_id] ? 'accepted' : 'rejected') as 'accepted' | 'rejected',
      }))
      return confirmProbabilisticReview(sessionId, { decisions })
    },
    onSuccess,
  })

  const reviewSheets = useMemo((): PanelSheet[] => {
    const rows = matches.map((m) => ({
      'Match ID':   m.match_id,
      'Grouping':   m.grouping_type,
      'Similarity': m.final_similarity,
      'GL IDs':     m.record_ids_A.join(', '),
      'Sub IDs':    m.record_ids_B.join(', '),
      'Decision':   checked[m.match_id] ? 'accepted' : 'rejected',
    }))
    return [{ id: 'matches', label: `Matches + Decisions (${rows.length})`, name: 'Prob Matches', rows }]
  }, [matches, checked])

  const hasPoolRecords =
    (cachedResult?.gl_pool_records?.length ?? 0) > 0 ||
    (cachedResult?.sub_pool_records?.length ?? 0) > 0

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Probabilistic Review</h2>
      <p className="text-sm text-gray-500 mb-2">
        Review each probabilistic match. Check to accept, uncheck to reject. Expand any match to
        inspect the full GL and Subledger record details.
      </p>
      <div className="bg-amber-50 border border-amber-100 rounded-md p-3 text-sm text-amber-700 mb-5">
        {matches.length} probabilistic{' '}
        {matches.length === 1 ? 'match' : 'matches'} pending review —{' '}
        <strong>{acceptedCount} accepted</strong> · <strong>{rejectedCount} rejected</strong>.
      </div>

      {/* Expand / collapse controls */}
      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={expandAll}
          className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-md transition-colors"
        >
          Expand All
        </button>
        <button
          onClick={collapseAll}
          className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-md transition-colors"
        >
          Collapse All
        </button>
      </div>

      {/* Bulk controls */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={checkAll}
          className="text-xs bg-green-100 hover:bg-green-200 text-green-700 px-3 py-1.5 rounded-md transition-colors"
        >
          Check All (Accept)
        </button>
        <button
          onClick={uncheckAll}
          className="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-3 py-1.5 rounded-md transition-colors"
        >
          Uncheck All (Reject)
        </button>
        {!hasPoolRecords && matches.length > 0 && (
          <span className="text-xs text-amber-600">
            Record details unavailable — re-run probabilistic matching to see full rows.
          </span>
        )}
      </div>

      {/* Match cards */}
      {matches.length > 0 ? (
        <div className="space-y-2 mb-5">
          {matches.map((m) => {
            const isChecked = checked[m.match_id] ?? true
            const isExpanded = expandedMatches.has(m.match_id)
            const glRecords = m.record_ids_A
              .map((id) => glLookup.get(id))
              .filter(Boolean) as Record<string, unknown>[]
            const subRecords = m.record_ids_B
              .map((id) => subLookup.get(id))
              .filter(Boolean) as Record<string, unknown>[]

            return (
              <div
                key={m.match_id}
                className={[
                  'border rounded-lg overflow-hidden transition-colors',
                  isChecked ? 'border-green-200' : 'border-red-200',
                ].join(' ')}
              >
                {/* Card header — always visible */}
                <div
                  className={[
                    'flex items-center gap-3 px-4 py-3',
                    isChecked ? 'bg-green-50' : 'bg-red-50',
                  ].join(' ')}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleMatch(m.match_id)}
                    className="w-4 h-4 rounded cursor-pointer accent-green-600 flex-shrink-0"
                  />

                  <div className="flex-1 min-w-0 flex flex-wrap items-center gap-2">
                    <span className="text-xs font-mono text-gray-700 truncate">{m.match_id}</span>
                    <span
                      className={[
                        'text-xs font-medium px-1.5 py-0.5 rounded whitespace-nowrap',
                        m.final_similarity >= 0.85
                          ? 'bg-green-100 text-green-700'
                          : m.final_similarity >= 0.70
                            ? 'bg-blue-100 text-blue-700'
                            : 'bg-amber-100 text-amber-700',
                      ].join(' ')}
                    >
                      {(m.final_similarity * 100).toFixed(1)}% similarity
                    </span>
                    <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded whitespace-nowrap">
                      {m.grouping_type}
                    </span>
                    <span className="text-xs text-gray-400">
                      {m.record_ids_A.length} GL · {m.record_ids_B.length} Sub
                    </span>
                  </div>

                  <span
                    className={[
                      'text-xs font-medium px-2 py-0.5 rounded whitespace-nowrap',
                      isChecked ? 'bg-green-200 text-green-800' : 'bg-red-200 text-red-800',
                    ].join(' ')}
                  >
                    {isChecked ? 'Accept' : 'Reject'}
                  </span>

                  <button
                    onClick={() => setExpandedMatches((prev) => {
                        const next = new Set(prev)
                        isExpanded ? next.delete(m.match_id) : next.add(m.match_id)
                        return next
                      })}
                    className="text-xs text-blue-500 hover:text-blue-700 px-2 py-1 rounded hover:bg-blue-50 transition-colors whitespace-nowrap"
                  >
                    {isExpanded ? 'Collapse ▲' : 'Expand ▼'}
                  </button>
                </div>

                {/* Expanded record detail */}
                {isExpanded && (
                  <div className="px-4 py-3 bg-white border-t border-gray-100 space-y-4">
                    <div>
                      <h5 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                        GL Records ({m.record_ids_A.length})
                      </h5>
                      {glRecords.length > 0 ? (
                        <RecordGrid records={glRecords} />
                      ) : (
                        <p className="text-xs text-gray-400 italic">
                          GL record details not cached — re-run probabilistic matching to populate.
                        </p>
                      )}
                    </div>

                    <div className="border-t border-gray-100 pt-4">
                      <h5 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                        Subledger Records ({m.record_ids_B.length})
                      </h5>
                      {subRecords.length > 0 ? (
                        <RecordGrid records={subRecords} />
                      ) : (
                        <p className="text-xs text-gray-400 italic">
                          Subledger record details not cached — re-run probabilistic matching to populate.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-md p-4 text-sm text-gray-500 mb-5">
          Match details not available — run probabilistic matching first in this session. You may
          still submit to advance the state with no decisions recorded.
        </div>
      )}

      {matches.length > 0 && (
        <div className="mb-5">
          <DownloadPanel filename="prob_review_decisions" sheets={reviewSheets} />
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
        {mutation.isPending
          ? 'Submitting…'
          : matches.length > 0
            ? `Submit Decisions (${acceptedCount} accept · ${rejectedCount} reject)`
            : 'Submit'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
