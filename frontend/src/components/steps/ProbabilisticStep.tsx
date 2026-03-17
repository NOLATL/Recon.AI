import { useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runProbabilistic } from '@/api/endpoints'
import type { ProbabilisticResponse, ProbabilisticMatch } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

function buildProbSheets(data: ProbabilisticResponse): PanelSheet[] {
  const s = data.summary
  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'Match Count',    Value: s.match_count },
    { Metric: 'GL Matched',     Value: s.matched_gl_records },
    { Metric: 'Sub Matched',    Value: s.matched_sub_records },
    { Metric: 'GL Residual',    Value: s.unmatched_gl_records },
    { Metric: 'Sub Residual',   Value: s.unmatched_sub_records },
    { Metric: 'Threshold Used', Value: `${(s.threshold_used * 100).toFixed(0)}%` },
    ...Object.entries(s.weights_used).map(([k, v]) => ({
      Metric: `Weight — ${k}`,
      Value: `${(v * 100).toFixed(0)}%`,
    })),
  ]
  const matchRows = data.matches.map((m) => ({
    'Match ID': m.match_id,
    'Grouping':  m.grouping_type,
    'Similarity': m.final_similarity,
    'GL IDs':    m.record_ids_A.join(', '),
    'Sub IDs':   m.record_ids_B.join(', '),
    'Status':    m.user_status,
    ...Object.fromEntries(
      Object.entries(m.component_scores).map(([k, v]) => [`Score — ${k}`, v]),
    ),
  }))
  return [
    { id: 'summary', label: 'Summary',                          name: 'Summary', rows: summaryRows },
    { id: 'matches', label: `Matches (${data.matches.length})`, name: 'Matches', rows: matchRows },
  ]
}

interface Props {
  sessionId: string
  onSuccess: () => void
}

function MatchesTable({ matches }: { matches: ProbabilisticMatch[] }) {
  if (matches.length === 0) {
    return <p className="text-sm text-white/50">No probabilistic matches found.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-void-elevated">
          <tr>
            <th className="text-left py-2 px-3 font-medium text-white/40">Match ID</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Grouping</th>
            <th className="text-right py-2 px-3 font-medium text-white/40">Similarity</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Component Scores</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">GL IDs</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Sub IDs</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-void-border/50">
          {matches.slice(0, 500).map((m) => (
            <tr key={m.match_id} className="hover:bg-void-elevated">
              <td className="py-2 px-3 font-mono text-white/75">{m.match_id}</td>
              <td className="py-2 px-3">
                <span className="bg-void-border px-1.5 py-0.5 rounded text-white/60">
                  {m.grouping_type}
                </span>
              </td>
              <td className="py-2 px-3 text-right font-medium">
                <span
                  className={
                    m.final_similarity >= 0.85
                      ? 'text-emerald-400'
                      : m.final_similarity >= 0.70
                        ? 'text-bdo-red-light'
                        : 'text-amber-300'
                  }
                >
                  {(m.final_similarity * 100).toFixed(1)}%
                </span>
              </td>
              <td className="py-2 px-3 text-white/50">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(m.component_scores).map(([k, v]) => (
                    <span key={k} className="bg-void-border border-void-border text-white/50 px-1 py-0.5 rounded text-[10px]">
                      {k}: {(v * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2 px-3 font-mono text-white/50 max-w-[100px] truncate">
                {m.record_ids_A.join(', ')}
              </td>
              <td className="py-2 px-3 font-mono text-white/50 max-w-[100px] truncate">
                {m.record_ids_B.join(', ')}
              </td>
              <td className="py-2 px-3">
                <span className="bg-amber-500/15 text-amber-300 px-1.5 py-0.5 rounded text-[10px]">
                  {m.user_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {matches.length > 500 && (
        <p className="text-xs text-white/35 p-3">Showing first 500 rows.</p>
      )}
    </div>
  )
}

function ProbResult({ data }: { data: ProbabilisticResponse }) {
  const s = data.summary
  const probSheets = useMemo(() => buildProbSheets(data), [data])
  return (
    <div className="mt-6 space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ['Matches', s.match_count],
          ['GL Matched', s.matched_gl_records],
          ['Sub Matched', s.matched_sub_records],
          ['GL Residual', s.unmatched_gl_records],
        ].map(([label, value]) => (
          <div key={String(label)} className="bg-void-elevated border border-void-border rounded-xl p-3 text-center">
            <p className="text-xs text-white/50">{label}</p>
            <p className="text-xl font-bold text-white">{value}</p>
          </div>
        ))}
      </div>

      <div className="flex gap-4 text-sm">
        <span className="text-white/50">
          Threshold: <strong>{(s.threshold_used * 100).toFixed(0)}%</strong>
        </span>
        <span className="text-white/50">
          Weights:{' '}
          {Object.entries(s.weights_used)
            .map(([k, v]) => `${k}: ${(v * 100).toFixed(0)}%`)
            .join(', ')}
        </span>
      </div>

      <div>
        <h4 className="text-sm font-medium text-white/70 mb-3">Probabilistic Matches</h4>
        <MatchesTable matches={data.matches} />
      </div>

      <DownloadPanel
        filename={`probabilistic_${data.session_id.slice(0, 8)}`}
        sheets={probSheets}
      />

      <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 text-sm text-amber-300">
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
      const key = `prob_result_${sessionId}`
      try {
        sessionStorage.setItem(key, JSON.stringify(data))
      } catch {
        try {
          sessionStorage.setItem(key, JSON.stringify({
            ...data,
            gl_pool_records: [],
            sub_pool_records: [],
          }))
        } catch {
          // Skip caching — review step shows fallback message
        }
      }
      onSuccess()
    },
  })

  return (
    <div className="glass-card p-6">
      <h2 className="text-base font-semibold text-white mb-1">Probabilistic Matching</h2>
      <p className="text-sm text-white/50 mb-5">
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
        className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {mutation.isPending ? 'Running…' : 'Run Probabilistic Matching'}
      </button>

      {mutation.data && <ProbResult data={mutation.data} />}
    </div>
  )
}
