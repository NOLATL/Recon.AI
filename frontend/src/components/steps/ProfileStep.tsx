import { useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runProfile } from '@/api/endpoints'
import type { ProfilingResponse, FileProfilingSummary } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function fmt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function FileCard({ summary }: { summary: FileProfilingSummary }) {
  return (
    <div className="border border-void-border rounded-xl p-4 bg-void-elevated">
      <h4 className="text-sm font-semibold text-white mb-3">{summary.file_key}</h4>

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="text-center">
          <p className="text-xs text-white/50">Rows</p>
          <p className="text-lg font-bold text-white">{summary.row_count.toLocaleString()}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-white/50">Duplicates</p>
          <p className="text-lg font-bold text-white">{summary.duplicate_row_count}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-white/50">Entities</p>
          <p className="text-lg font-bold text-white">
            {Object.keys(summary.entity_distribution).length}
          </p>
        </div>
      </div>

      {/* Numeric distributions */}
      {Object.keys(summary.numeric_distributions).length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-medium text-white/50 mb-1">Numeric Distributions</p>
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead>
                <tr className="text-white/40 border-b border-void-border">
                  <th className="text-left py-1 pr-3">Column</th>
                  <th className="text-right py-1 pr-2">Min</th>
                  <th className="text-right py-1 pr-2">Max</th>
                  <th className="text-right py-1 pr-2">Mean</th>
                  <th className="text-right py-1">Sum</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.numeric_distributions).map(([col, dist]) => (
                  <tr key={col} className="border-b border-void-border/50">
                    <td className="py-1 pr-3 font-mono text-white/70">{col}</td>
                    <td className="text-right py-1 pr-2 text-white/60">{fmt(dist.min)}</td>
                    <td className="text-right py-1 pr-2 text-white/60">{fmt(dist.max)}</td>
                    <td className="text-right py-1 pr-2 text-white/60">{fmt(dist.mean)}</td>
                    <td className="text-right py-1 text-white/60">{fmt(dist.sum)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Date ranges */}
      {Object.keys(summary.date_ranges).length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-medium text-white/50 mb-1">Date Ranges</p>
          <div className="space-y-1">
            {Object.entries(summary.date_ranges).map(([col, range]) => (
              <div key={col} className="flex justify-between text-xs">
                <span className="font-mono text-white/60">{col}</span>
                <span className="text-white/40">
                  {range.min ?? '—'} → {range.max ?? '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Null counts */}
      {Object.keys(summary.null_counts).length > 0 && (
        <div>
          <p className="text-xs font-medium text-white/50 mb-1">Null Counts</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(summary.null_counts)
              .filter(([, c]) => c > 0)
              .map(([col, count]) => (
                <span
                  key={col}
                  className="text-xs bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2 py-0.5 rounded"
                >
                  {col}: {count} ({fmt(summary.null_percentages[col])}%)
                </span>
              ))}
            {Object.values(summary.null_counts).every((c) => c === 0) && (
              <span className="text-xs text-emerald-400">No nulls</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ProfileResult({ data, sessionId }: { data: ProfilingResponse; sessionId: string }) {
  const sheets = useMemo(() => buildProfileSheets(data), [data])

  return (
    <div className="mt-6 space-y-5">
      {/* Narrative */}
      <div className="bg-bdo-red/8 border border-bdo-red/20 rounded-xl p-4">
        <p className="text-sm font-medium text-bdo-red-light mb-1">Narrative</p>
        <p className="text-sm text-white/70 whitespace-pre-wrap">{data.narrative}</p>
      </div>

      {/* Cross-file summary */}
      <div>
        <h4 className="text-sm font-medium text-white/70 mb-2">Cross-File Summary</h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="bg-void-elevated border border-void-border rounded-lg p-3 text-center">
            <p className="text-xs text-white/50">GL Rows</p>
            <p className="text-lg font-bold text-white">{data.metrics.cross_file.gl_row_count.toLocaleString()}</p>
          </div>
          <div className="bg-void-elevated border border-void-border rounded-lg p-3 text-center">
            <p className="text-xs text-white/50">Sub Rows</p>
            <p className="text-lg font-bold text-white">{data.metrics.cross_file.subledger_row_count.toLocaleString()}</p>
          </div>
          <div className="bg-void-elevated border border-void-border rounded-lg p-3 text-center">
            <p className="text-xs text-white/50">Delta</p>
            <p className="text-lg font-bold text-white">{data.metrics.cross_file.row_count_delta}</p>
          </div>
          <div className="bg-void-elevated border border-void-border rounded-lg p-3 text-center">
            <p className="text-xs text-white/50">Delta %</p>
            <p className="text-lg font-bold text-white">{fmt(data.metrics.cross_file.row_count_delta_pct)}%</p>
          </div>
        </div>
      </div>

      {/* Per-file */}
      <div>
        <h4 className="text-sm font-medium text-white/70 mb-2">Per-File Metrics</h4>
        <div className="space-y-4">
          {Object.values(data.metrics.files).map((f) => (
            <FileCard key={f.file_key} summary={f} />
          ))}
        </div>
      </div>

      <DownloadPanel
        filename={`profile_report_${sessionId.slice(0, 8)}`}
        sheets={sheets}
      />

      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-sm text-emerald-300">
        Profiling complete. State: <strong className="text-white">{data.state}</strong>
      </div>
    </div>
  )
}

const FILE_LABELS: Record<string, string> = {
  chart_of_accounts: 'Chart of Accounts',
  gl: 'General Ledger',
  subledger: 'Subledger',
}

// ── Download sheet builders ───────────────────────────────────────────────────

function buildProfileSheets(data: ProfilingResponse): PanelSheet[] {
  const cf = data.metrics.cross_file
  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'GL Row Count',   Value: cf.gl_row_count },
    { Metric: 'Sub Row Count',  Value: cf.subledger_row_count },
    { Metric: 'Row Delta',      Value: cf.row_count_delta },
    { Metric: 'Row Delta %',    Value: cf.row_count_delta_pct },
    { Metric: 'Narrative',      Value: data.narrative },
  ]

  const fileSheets: PanelSheet[] = Object.entries(data.metrics.files).map(([key, f]) => {
    const label = FILE_LABELS[key] ?? key
    const rows: Record<string, unknown>[] = [
      { Category: 'Overview', Column: 'Row Count',       Value: f.row_count },
      { Category: 'Overview', Column: 'Duplicate Rows',  Value: f.duplicate_row_count },
      ...Object.entries(f.null_counts).map(([col, count]) => ({
        Category: 'Null Count',
        Column: col,
        Count: count,
        'Null %': f.null_percentages[col] ?? 0,
      })),
      ...Object.entries(f.numeric_distributions).map(([col, d]) => ({
        Category: 'Numeric Distribution',
        Column: col,
        Min: d.min,
        Max: d.max,
        Mean: d.mean,
        Median: d.median,
        'Std Dev': d.std,
        Sum: d.sum,
      })),
      ...Object.entries(f.date_ranges).map(([col, dr]) => ({
        Category: 'Date Range',
        Column: col,
        'Min Date': dr.min,
        'Max Date': dr.max,
      })),
      ...Object.entries(f.entity_distribution).map(([entity, count]) => ({
        Category: 'Entity Distribution',
        Column: entity,
        Count: count,
      })),
    ]
    return { id: key, label, name: label.slice(0, 31), rows }
  })

  return [
    { id: 'summary', label: 'Cross-File Summary', name: 'Summary', rows: summaryRows },
    ...fileSheets,
  ]
}

function UploadConfirmation({ sessionId }: { sessionId: string }) {
  const raw = sessionStorage.getItem(`upload_result_${sessionId}`)
  if (!raw) return null

  const result = JSON.parse(raw) as {
    row_counts: Record<string, number>
    validation: Record<string, { is_valid: boolean; columns_validated: string[] }>
  }

  return (
    <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 mb-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-emerald-400 font-semibold text-sm">✓ Files loaded successfully</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {Object.entries(result.row_counts).map(([key, count]) => {
          const isValid = result.validation[key]?.is_valid ?? true
          return (
            <div key={key} className="bg-void-elevated border border-void-border rounded-lg p-3">
              <p className="text-xs text-white/50">{FILE_LABELS[key] ?? key}</p>
              <p className="text-xl font-bold text-white mt-0.5">{count.toLocaleString()}</p>
              <p className="text-xs text-white/35">rows</p>
              {!isValid && (
                <p className="text-xs text-bdo-red-light mt-1">Validation issues</p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function ProfileStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runProfile(sessionId),
    onSuccess: (data) => {
      const key = `profile_result_${sessionId}`
      try {
        sessionStorage.setItem(key, JSON.stringify(data))
      } catch {
        try {
          // Slim: strip per-file distribution maps (can be large with many unique values)
          const slim = {
            ...data,
            metrics: {
              ...data.metrics,
              files: Object.fromEntries(
                Object.entries(data.metrics.files).map(([k, v]) => [
                  k,
                  { ...v, entity_distribution: {}, numeric_distributions: {}, date_ranges: {} },
                ]),
              ),
            },
          }
          sessionStorage.setItem(key, JSON.stringify(slim))
        } catch {
          // Skip caching — preprocess step shows fallback message
        }
      }
      onSuccess()
    },
  })

  return (
    <div className="glass-card p-6">
      <UploadConfirmation sessionId={sessionId} />

      <h2 className="text-base font-semibold text-white mb-1">Profile Data</h2>
      <p className="text-sm text-white/50 mb-5">
        Analyze the uploaded files — row counts, nulls, duplicates, distributions.
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
        {mutation.isPending ? 'Profiling…' : 'Run Profile'}
      </button>

      {mutation.data && <ProfileResult data={mutation.data} sessionId={sessionId} />}
    </div>
  )
}
