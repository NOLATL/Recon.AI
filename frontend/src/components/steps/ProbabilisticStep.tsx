import { useMutation } from '@tanstack/react-query'
import { runProbabilistic } from '@/api/endpoints'
import type { ProbabilisticResponse, ProbabilisticMatch } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function MatchesTable({ matches }: { matches: ProbabilisticMatch[] }) {
  if (matches.length === 0) {
    return <p className="text-sm text-gray-500">No probabilistic matches found.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-50">
          <tr>
            <th className="text-left py-2 px-3 font-medium text-gray-600">Match ID</th>
            <th className="text-left py-2 px-3 font-medium text-gray-600">Grouping</th>
            <th className="text-right py-2 px-3 font-medium text-gray-600">Similarity</th>
            <th className="text-left py-2 px-3 font-medium text-gray-600">Component Scores</th>
            <th className="text-left py-2 px-3 font-medium text-gray-600">GL IDs</th>
            <th className="text-left py-2 px-3 font-medium text-gray-600">Sub IDs</th>
            <th className="text-left py-2 px-3 font-medium text-gray-600">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {matches.slice(0, 500).map((m) => (
            <tr key={m.match_id} className="hover:bg-gray-50">
              <td className="py-2 px-3 font-mono text-gray-700">{m.match_id}</td>
              <td className="py-2 px-3">
                <span className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                  {m.grouping_type}
                </span>
              </td>
              <td className="py-2 px-3 text-right font-medium">
                <span
                  className={
                    m.final_similarity >= 0.85
                      ? 'text-green-600'
                      : m.final_similarity >= 0.70
                        ? 'text-blue-600'
                        : 'text-amber-600'
                  }
                >
                  {(m.final_similarity * 100).toFixed(1)}%
                </span>
              </td>
              <td className="py-2 px-3 text-gray-500">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(m.component_scores).map(([k, v]) => (
                    <span key={k} className="bg-gray-50 border border-gray-200 px-1 py-0.5 rounded text-[10px]">
                      {k}: {(v * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2 px-3 font-mono text-gray-500 max-w-[100px] truncate">
                {m.record_ids_A.join(', ')}
              </td>
              <td className="py-2 px-3 font-mono text-gray-500 max-w-[100px] truncate">
                {m.record_ids_B.join(', ')}
              </td>
              <td className="py-2 px-3">
                <span className="bg-amber-50 text-amber-700 px-1.5 py-0.5 rounded text-[10px]">
                  {m.user_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {matches.length > 500 && (
        <p className="text-xs text-gray-400 p-3">Showing first 500 rows.</p>
      )}
    </div>
  )
}

function ProbResult({ data }: { data: ProbabilisticResponse }) {
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

      <div className="flex gap-4 text-sm">
        <span className="text-gray-500">
          Threshold: <strong>{(s.threshold_used * 100).toFixed(0)}%</strong>
        </span>
        <span className="text-gray-500">
          Weights:{' '}
          {Object.entries(s.weights_used)
            .map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`)
            .join(', ')}
        </span>
      </div>

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">Probabilistic Matches</h4>
        <MatchesTable matches={data.matches} />
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-md p-3 text-sm text-amber-800">
        Probabilistic matching complete. State: <strong>{data.state}</strong>. Proceed to
        Probabilistic Review to accept or reject each match.
      </div>
    </div>
  )
}

export default function ProbabilisticStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runProbabilistic(sessionId),
    onSuccess: (data) => {
      // Cache matches for ProbabilisticReviewStep
      sessionStorage.setItem(`prob_matches_${sessionId}`, JSON.stringify(data.matches))
      onSuccess()
    },
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Probabilistic Matching</h2>
      <p className="text-sm text-gray-500 mb-5">
        Run weighted fuzzy matching (1:1, N:1, 1:N) on the deterministic residual pool. Results
        require human review before acceptance.
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
        {mutation.isPending ? 'Running…' : 'Run Probabilistic Matching'}
      </button>

      {mutation.data && <ProbResult data={mutation.data} />}
    </div>
  )
}
