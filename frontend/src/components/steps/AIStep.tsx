import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runAI } from '@/api/endpoints'
import type { AIResponse, AIMatch } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

function buildAISheets(data: AIResponse): PanelSheet[] {
  const s = data.summary
  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'Suggestion Count', Value: s.suggestion_count },
    { Metric: 'Residual GL',      Value: s.total_residual_gl },
    { Metric: 'Residual Sub',     Value: s.total_residual_sub },
    { Metric: 'Model Used',       Value: s.model_used },
    { Metric: 'Prompt Version',   Value: s.prompt_version },
  ]
  const suggestionRows = data.suggestions.map((m) => ({
    'Match ID':        m.match_id,
    'Grouping':        m.grouping_type,
    'AI Confidence':   m.ai_confidence_score,
    'Materiality':     m.materiality,
    'GL IDs':          m.record_ids_A.join(', '),
    'Sub IDs':         m.record_ids_B.join(', '),
    'Reasoning':       m.reasoning_narrative,
    'Status':          m.user_status,
  }))
  return [
    { id: 'summary',     label: 'Summary',                                 name: 'Summary',     rows: summaryRows },
    { id: 'suggestions', label: `AI Suggestions (${data.suggestions.length})`, name: 'AI Suggestions', rows: suggestionRows },
  ]
}

interface Props {
  sessionId: string
  onSuccess: () => void
}

function NarrativeCell({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const preview = text.length > 80 ? text.slice(0, 80) + '…' : text
  return (
    <div>
      <p className="text-white/60">{open ? text : preview}</p>
      {text.length > 80 && (
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-bdo-red/70 hover:text-bdo-red-light text-[10px] mt-0.5"
        >
          {open ? 'Collapse' : 'Expand'}
        </button>
      )}
    </div>
  )
}

function AIMatchesTable({ suggestions }: { suggestions: AIMatch[] }) {
  if (suggestions.length === 0) {
    return <p className="text-sm text-white/50">No AI suggestions generated.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-void-elevated">
          <tr>
            <th className="text-left py-2 px-3 font-medium text-white/40">Match ID</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Grouping</th>
            <th className="text-right py-2 px-3 font-medium text-white/40">AI Confidence</th>
            <th className="text-right py-2 px-3 font-medium text-white/40">Materiality</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">GL IDs</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Sub IDs</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Reasoning</th>
            <th className="text-left py-2 px-3 font-medium text-white/40">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-void-border/50">
          {suggestions.map((m) => (
            <tr key={m.match_id} className="hover:bg-void-elevated align-top">
              <td className="py-2 px-3 font-mono text-white/75">{m.match_id}</td>
              <td className="py-2 px-3 text-white/60">{m.grouping_type}</td>
              <td className="py-2 px-3 text-right font-medium">
                <span
                  className={
                    m.ai_confidence_score >= 0.8
                      ? 'text-emerald-400'
                      : m.ai_confidence_score >= 0.6
                        ? 'text-amber-300'
                        : 'text-bdo-red-light'
                  }
                >
                  {(m.ai_confidence_score * 100).toFixed(0)}%
                </span>
              </td>
              <td className="py-2 px-3 text-right text-white/60">
                {m.materiality.toFixed(2)}
              </td>
              <td className="py-2 px-3 font-mono text-white/50 max-w-[80px] truncate">
                {m.record_ids_A.join(', ')}
              </td>
              <td className="py-2 px-3 font-mono text-white/50 max-w-[80px] truncate">
                {m.record_ids_B.join(', ')}
              </td>
              <td className="py-2 px-3 max-w-[220px]">
                <NarrativeCell text={m.reasoning_narrative} />
              </td>
              <td className="py-2 px-3">
                <span className="bg-violet-500/15 text-violet-300 px-1.5 py-0.5 rounded text-[10px]">
                  {m.user_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AIResult({ data }: { data: AIResponse }) {
  const s = data.summary
  const aiSheets = useMemo(() => buildAISheets(data), [data])
  return (
    <div className="mt-6 space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          ['Suggestions', s.suggestion_count],
          ['Residual GL', s.total_residual_gl],
          ['Residual Sub', s.total_residual_sub],
          ['Model', s.model_used],
          ['Prompt Ver.', s.prompt_version],
        ].map(([label, value]) => (
          <div key={String(label)} className="bg-void-elevated border border-void-border rounded-xl p-3 text-center">
            <p className="text-xs text-white/50">{label}</p>
            <p className="text-sm font-bold text-white mt-0.5 truncate">{value}</p>
          </div>
        ))}
      </div>

      <div className="bg-violet-500/10 border border-violet-500/20 rounded-xl p-3 text-sm text-violet-300">
        AI suggestions are <strong>advisory only</strong>. All suggestions must be reviewed before
        acceptance. The residual pool is not modified by this step.
      </div>

      <div>
        <h4 className="text-sm font-medium text-white/70 mb-3">AI Suggestions</h4>
        <AIMatchesTable suggestions={data.suggestions} />
      </div>

      <DownloadPanel
        filename={`ai_suggestions_${data.session_id.slice(0, 8)}`}
        sheets={aiSheets}
      />

      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-sm text-emerald-300">
        AI phase complete. State: <strong>{data.state}</strong>. Proceed to AI Review.
      </div>
    </div>
  )
}

export default function AIStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runAI(sessionId),
    onSuccess: (data) => {
      const key = `ai_result_${sessionId}`
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
      <h2 className="text-base font-semibold text-white mb-1">AI Suggested Matches</h2>
      <p className="text-sm text-white/50 mb-5">
        Generate AI-assisted match suggestions for records remaining in the residual pool. Results
        are advisory only and require human review.
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
        {mutation.isPending ? 'Generating AI suggestions…' : 'Run AI Matching'}
      </button>

      {mutation.data && <AIResult data={mutation.data} />}
    </div>
  )
}
