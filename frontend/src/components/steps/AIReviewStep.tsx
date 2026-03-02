import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { confirmAIReview } from '@/api/endpoints'
import type { AIResponse, AIReviewResponse } from '@/schemas'
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

// ── Main step ───────────────────────────────────────────────────────────────

export default function AIReviewStep({ sessionId, onSuccess }: Props) {
  // Load the full result cached by AIStep
  const cachedRaw = sessionStorage.getItem(`ai_result_${sessionId}`)
  const cachedResult: AIResponse | null = cachedRaw ? JSON.parse(cachedRaw) : null
  const suggestions = cachedResult?.suggestions ?? []

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
    suggestions.forEach((m) => { init[m.match_id] = true })
    return init
  })

  const [expandedMatches, setExpandedMatches] = useState<Set<string>>(new Set())

  const expandAll = () => setExpandedMatches(new Set(suggestions.map((m) => m.match_id)))
  const collapseAll = () => setExpandedMatches(new Set())

  const toggleMatch = (matchId: string) =>
    setChecked((prev) => ({ ...prev, [matchId]: !prev[matchId] }))

  const checkAll = () => {
    const next: Record<string, boolean> = {}
    suggestions.forEach((m) => { next[m.match_id] = true })
    setChecked(next)
  }

  const uncheckAll = () => {
    const next: Record<string, boolean> = {}
    suggestions.forEach((m) => { next[m.match_id] = false })
    setChecked(next)
  }

  const acceptedCount = suggestions.filter((m) => checked[m.match_id]).length
  const rejectedCount = suggestions.length - acceptedCount

  const mutation = useMutation({
    mutationFn: () => {
      const decisions = suggestions.map((m) => ({
        match_id: m.match_id,
        decision: (checked[m.match_id] ? 'accepted' : 'rejected') as 'accepted' | 'rejected',
      }))
      return confirmAIReview(sessionId, { decisions })
    },
    onSuccess,
  })

  const reviewSheets = useMemo((): PanelSheet[] => {
    const rows = suggestions.map((m) => ({
      'Match ID':      m.match_id,
      'Grouping':      m.grouping_type,
      'AI Confidence': m.ai_confidence_score,
      'Materiality':   m.materiality,
      'GL IDs':        m.record_ids_A.join(', '),
      'Sub IDs':       m.record_ids_B.join(', '),
      'Reasoning':     m.reasoning_narrative,
      'Decision':      checked[m.match_id] ? 'accepted' : 'rejected',
    }))
    return [{ id: 'suggestions', label: `Suggestions + Decisions (${rows.length})`, name: 'AI Review', rows }]
  }, [suggestions, checked])

  const hasPoolRecords =
    (cachedResult?.gl_pool_records?.length ?? 0) > 0 ||
    (cachedResult?.sub_pool_records?.length ?? 0) > 0

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">AI Review</h2>
      <p className="text-sm text-gray-500 mb-2">
        Review each AI suggestion. Check to accept, uncheck to reject. Expand any suggestion to read
        the AI narrative and inspect the full GL and Subledger record details.
      </p>
      <div className="bg-purple-50 border border-purple-100 rounded-md p-3 text-sm text-purple-800 mb-5">
        {suggestions.length} AI{' '}
        {suggestions.length === 1 ? 'suggestion' : 'suggestions'} pending review —{' '}
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
        {!hasPoolRecords && suggestions.length > 0 && (
          <span className="text-xs text-amber-600">
            Record details unavailable — re-run AI matching to see full rows.
          </span>
        )}
      </div>

      {/* Suggestion cards */}
      {suggestions.length > 0 ? (
        <div className="space-y-2 mb-5">
          {suggestions.map((m) => {
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
                        m.ai_confidence_score >= 0.8
                          ? 'bg-green-100 text-green-700'
                          : m.ai_confidence_score >= 0.6
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-red-100 text-red-700',
                      ].join(' ')}
                    >
                      {(m.ai_confidence_score * 100).toFixed(0)}% confidence
                    </span>
                    <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded whitespace-nowrap">
                      {m.grouping_type}
                    </span>
                    <span className="text-xs text-gray-400 whitespace-nowrap">
                      materiality {m.materiality.toFixed(2)}
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

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="px-4 py-3 bg-white border-t border-gray-100 space-y-4">
                    {/* AI Narrative */}
                    <div>
                      <h5 className="text-[11px] font-semibold text-purple-600 uppercase tracking-wide mb-1.5">
                        AI Reasoning Narrative
                      </h5>
                      <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap bg-purple-50 border border-purple-100 rounded p-3">
                        {m.reasoning_narrative || 'No narrative provided.'}
                      </p>
                    </div>

                    {/* GL Records */}
                    <div className="border-t border-gray-100 pt-4">
                      <h5 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                        GL Records ({m.record_ids_A.length})
                      </h5>
                      {glRecords.length > 0 ? (
                        <RecordGrid records={glRecords} />
                      ) : (
                        <p className="text-xs text-gray-400 italic">
                          GL record details not cached — re-run AI matching to populate.
                        </p>
                      )}
                    </div>

                    {/* Sub Records */}
                    <div className="border-t border-gray-100 pt-4">
                      <h5 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                        Subledger Records ({m.record_ids_B.length})
                      </h5>
                      {subRecords.length > 0 ? (
                        <RecordGrid records={subRecords} />
                      ) : (
                        <p className="text-xs text-gray-400 italic">
                          Subledger record details not cached — re-run AI matching to populate.
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
          AI suggestion details not available — run the AI step first in this session. You may still
          submit to advance the state with no decisions recorded.
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mb-5">
          <DownloadPanel filename="ai_review_decisions" sheets={reviewSheets} />
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
        {mutation.isPending
          ? 'Submitting…'
          : suggestions.length > 0
            ? `Submit Decisions (${acceptedCount} accept · ${rejectedCount} reject)`
            : 'Submit'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
