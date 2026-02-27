import { useMutation } from '@tanstack/react-query'
import { confirmDeterministicReview } from '@/api/endpoints'
import type { DeterministicReviewResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function ReviewResult({ data }: { data: DeterministicReviewResponse }) {
  return (
    <div className="mt-5 space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[
          ['Deterministic Matches', data.deterministic_match_count],
          ['GL Residual', data.residual_gl_count],
          ['Sub Residual', data.residual_sub_count],
        ].map(([label, value]) => (
          <div key={String(label)} className="bg-gray-50 rounded-md p-4 text-center">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
          </div>
        ))}
      </div>
      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Review confirmed. State: <strong>{data.state}</strong>. Snapshot key:{' '}
        <span className="font-mono">{data.snapshot.key}</span>
      </div>
    </div>
  )
}

export default function DeterministicReviewStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => confirmDeterministicReview(sessionId),
    onSuccess,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Deterministic Review — Confirm</h2>
      <p className="text-sm text-gray-500 mb-2">
        Review the deterministic match results. This step is <strong>confirm-only</strong> — no
        recomputation occurs. A snapshot is captured before the state advances.
      </p>
      <div className="bg-amber-50 border border-amber-100 rounded-md p-3 text-sm text-amber-800 mb-5">
        Deterministic matches are authoritative and auto-confirmed. Confirming here advances the
        session to allow probabilistic matching on the residual records.
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
        {mutation.isPending ? 'Confirming…' : 'Confirm Deterministic Review'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
