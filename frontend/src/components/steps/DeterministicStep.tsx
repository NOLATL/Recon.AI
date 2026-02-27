import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runDeterministic } from '@/api/endpoints'
import type { DeterministicResponse, MatchRecord } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function MatchesTable({ matches }: { matches: MatchRecord[] }) {
  const [groupFilter, setGroupFilter] = useState('')
  const [scenarioFilter, setScenarioFilter] = useState<number | ''>('')
  const [minConf, setMinConf] = useState(0)

  const uniqueGroups = [...new Set(matches.map((m) => m.grouping_type))]
  const uniqueScenarios = [...new Set(matches.map((m) => m.scenario_id))].sort((a, b) => a - b)

  const filtered = matches.filter((m) => {
    if (groupFilter && m.grouping_type !== groupFilter) return false
    if (scenarioFilter !== '' && m.scenario_id !== scenarioFilter) return false
    if (m.confidence_score < minConf) return false
    return true
  })

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Grouping type</label>
          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300"
          >
            <option value="">All</option>
            {uniqueGroups.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Scenario</label>
          <select
            value={String(scenarioFilter)}
            onChange={(e) => setScenarioFilter(e.target.value === '' ? '' : Number(e.target.value))}
            className="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-300"
          >
            <option value="">All</option>
            {uniqueScenarios.map((s) => (
              <option key={s} value={s}>Scenario {s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">
            Min confidence: {(minConf * 100).toFixed(0)}%
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minConf}
            onChange={(e) => setMinConf(Number(e.target.value))}
            className="w-32"
          />
        </div>
      </div>

      <p className="text-xs text-gray-400 mb-2">
        {filtered.length} of {matches.length} matches
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left py-2 px-3 font-medium text-gray-600">Match ID</th>
              <th className="text-left py-2 px-3 font-medium text-gray-600">Scenario</th>
              <th className="text-left py-2 px-3 font-medium text-gray-600">Grouping</th>
              <th className="text-right py-2 px-3 font-medium text-gray-600">Confidence</th>
              <th className="text-left py-2 px-3 font-medium text-gray-600">GL IDs</th>
              <th className="text-left py-2 px-3 font-medium text-gray-600">Sub IDs</th>
              <th className="text-left py-2 px-3 font-medium text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.slice(0, 500).map((m) => (
              <tr key={m.match_id} className="hover:bg-gray-50">
                <td className="py-2 px-3 font-mono text-gray-700">{m.match_id}</td>
                <td className="py-2 px-3 text-gray-600">
                  <div className="font-medium">S{m.scenario_id}</div>
                  <div className="text-gray-400 max-w-[160px] truncate" title={m.scenario_description}>
                    {m.scenario_description}
                  </div>
                </td>
                <td className="py-2 px-3">
                  <span className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                    {m.grouping_type}
                  </span>
                </td>
                <td className="py-2 px-3 text-right font-medium">
                  <span
                    className={
                      m.confidence_score >= 0.95
                        ? 'text-green-600'
                        : m.confidence_score >= 0.75
                          ? 'text-blue-600'
                          : 'text-amber-600'
                    }
                  >
                    {(m.confidence_score * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="py-2 px-3 font-mono text-gray-500 max-w-[120px] truncate">
                  {m.record_ids_A.join(', ')}
                </td>
                <td className="py-2 px-3 font-mono text-gray-500 max-w-[120px] truncate">
                  {m.record_ids_B.join(', ')}
                </td>
                <td className="py-2 px-3">
                  <span className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-[10px]">
                    {m.user_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length > 500 && (
          <p className="text-xs text-gray-400 p-3">Showing first 500 rows. Use filters to narrow results.</p>
        )}
      </div>
    </div>
  )
}

function DeterministicResult({ data }: { data: DeterministicResponse }) {
  const s = data.summary
  return (
    <div className="mt-6 space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ['Matches', s.match_count],
          ['GL Matched', s.matched_gl_records],
          ['Sub Matched', s.matched_sub_records],
          ['GL Residual', s.unmatched_gl_records],
        ].map(([label, value]) => (
          <div key={String(label)} className="bg-gray-50 rounded-md p-3 text-center">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-xl font-bold text-gray-900">{value}</p>
          </div>
        ))}
      </div>

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-1">Scenario Breakdown</h4>
        <div className="flex flex-wrap gap-2">
          {Object.entries(s.scenario_counts).map(([sc, count]) => (
            <span key={sc} className="bg-blue-50 text-blue-700 text-xs px-3 py-1 rounded-full">
              {sc}: {count}
            </span>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">Matches</h4>
        <MatchesTable matches={data.matches} />
      </div>

      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Deterministic matching complete. State: <strong>{data.state}</strong>. Proceed to Deterministic
        Review to confirm.
      </div>
    </div>
  )
}

export default function DeterministicStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runDeterministic(sessionId),
    onSuccess,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Deterministic Matching</h2>
      <p className="text-sm text-gray-500 mb-5">
        Run rule-based matching across 4 scenarios (exact → date tolerance → entity → N:1). Results
        are authoritative and auto-confirmed.
      </p>

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
        {mutation.isPending ? 'Running…' : 'Run Deterministic Matching'}
      </button>

      {mutation.data && <DeterministicResult data={mutation.data} />}
    </div>
  )
}
