import { useMutation } from '@tanstack/react-query'
import { runConsolidate } from '@/api/endpoints'
import type { FinalConsolidationResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function ConsolidationResult({ data }: { data: FinalConsolidationResponse }) {
  const s = data.summary
  const total = s.total_match_count
  return (
    <div className="mt-6 space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Matches', value: s.total_match_count, color: 'blue' },
          { label: 'Deterministic', value: s.deterministic_match_count, color: 'green' },
          { label: 'Probabilistic', value: s.probabilistic_match_count, color: 'blue' },
          { label: 'AI', value: s.ai_match_count, color: 'purple' },
        ].map(({ label, value, color }) => (
          <div key={label} className={`bg-${color}-50 border border-${color}-100 rounded-md p-4 text-center`}>
            <p className={`text-xs text-${color}-600`}>{label}</p>
            <p className={`text-2xl font-bold text-${color}-800`}>{value}</p>
            {total > 0 && value !== total && (
              <p className={`text-xs text-${color}-500 mt-0.5`}>
                {((value / total) * 100).toFixed(1)}%
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-center">
          <p className="text-xs text-gray-500">Residual GL</p>
          <p className="text-xl font-bold text-gray-700">{s.residual_gl_count}</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-center">
          <p className="text-xs text-gray-500">Residual Sub</p>
          <p className="text-xl font-bold text-gray-700">{s.residual_sub_count}</p>
        </div>
        <div className="bg-red-50 border border-red-100 rounded-md p-3 text-center">
          <p className="text-xs text-red-500">Rejected</p>
          <p className="text-xl font-bold text-red-700">{s.rejected_count}</p>
        </div>
      </div>

      {s.override_count > 0 && (
        <div className="bg-amber-50 border border-amber-100 rounded-md p-3 text-sm text-amber-800">
          {s.override_count} override(s) recorded.
        </div>
      )}

      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Final consolidation complete. State: <strong>{data.state}</strong>. Proceed to Export to
        generate output files.
      </div>
    </div>
  )
}

export default function ConsolidateStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runConsolidate(sessionId),
    onSuccess,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Final Consolidation</h2>
      <p className="text-sm text-gray-500 mb-2">
        Assemble the complete reconciliation dataset from all accepted matches across deterministic,
        probabilistic, and AI layers.
      </p>
      <div className="bg-blue-50 border border-blue-100 rounded-md p-3 text-sm text-blue-800 mb-5">
        This is a pure bookkeeping step — no recomputation occurs. A snapshot is captured before the
        state advances.
      </div>

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
        {mutation.isPending ? 'Consolidating…' : 'Run Final Consolidation'}
      </button>

      {mutation.data && <ConsolidationResult data={mutation.data} />}
    </div>
  )
}
