import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runPreprocess } from '@/api/endpoints'
import type {
  PreprocessingResponse,
  ProfilingResponse,
  NormalizationEntry,
  FileProfilingSummary,
} from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

interface Props {
  sessionId: string
  onSuccess: () => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function n(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—'
  return v.toLocaleString(undefined, { maximumFractionDigits: decimals })
}

function pctColor(pct: number): string {
  if (pct === 0) return 'bg-green-400'
  if (pct < 5) return 'bg-yellow-400'
  if (pct < 20) return 'bg-orange-400'
  return 'bg-red-500'
}

const FILE_LABELS: Record<string, string> = {
  chart_of_accounts: 'Chart of Accounts',
  gl: 'General Ledger',
  subledger: 'Subledger',
}

// ── Download sheet builders ───────────────────────────────────────────────────

function buildProfileSheets(profile: ProfilingResponse, sessionId: string): PanelSheet[] {
  const cf = profile.metrics.cross_file
  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'Session ID',     Value: sessionId },
    { Metric: 'State',          Value: profile.state },
    { Metric: 'Snapshot Key',   Value: profile.snapshot.key },
    { Metric: 'Generated',      Value: new Date().toISOString() },
    { Metric: 'GL Row Count',   Value: cf.gl_row_count },
    { Metric: 'Sub Row Count',  Value: cf.subledger_row_count },
    { Metric: 'Row Delta',      Value: cf.row_count_delta },
    { Metric: 'Row Delta %',    Value: cf.row_count_delta_pct },
    { Metric: 'Narrative',      Value: profile.narrative },
  ]

  const fileSheets: PanelSheet[] = Object.entries(profile.metrics.files).map(([key, f]) => {
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
    { id: 'summary', label: 'Summary & Log', name: 'Summary', rows: summaryRows },
    ...fileSheets,
  ]
}

function buildVendorMapSheets(data: PreprocessingResponse): PanelSheet[] {
  const mapRows = data.vendor_normalization_map.map((e) => ({
    'Original Vendor':   e.original_vendor,
    'Normalized Vendor': e.normalized_vendor,
    'Matched To':        e.matched_to ?? '',
    'Match Source':      e.match_source,
    'Similarity Score':  e.similarity_score != null
      ? `${(e.similarity_score * 100).toFixed(1)}%`
      : '',
    'AI Confidence':     e.ai_confidence_score != null
      ? `${(e.ai_confidence_score * 100).toFixed(1)}%`
      : '',
  }))

  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'Total GL Vendors',  Value: data.normalization_summary.total_unique_gl_vendors },
    { Metric: 'Tier 1 (Rules)',    Value: data.normalization_summary.tier1_count },
    { Metric: 'Tier 2 (Fuzzy)',    Value: data.normalization_summary.tier2_count },
    { Metric: 'Tier 3 (AI Stub)',  Value: data.normalization_summary.tier3_count },
    { Metric: 'Threshold',         Value: `${(data.normalization_summary.threshold_used * 100).toFixed(0)}%` },
    { Metric: 'Alias Version',     Value: data.normalization_summary.alias_version },
  ]

  return [
    { id: 'vendor_map', label: 'Vendor Normalization Map', name: 'Vendor Map', rows: mapRows },
    { id: 'norm_summary', label: 'Normalization Summary', name: 'Norm Summary', rows: summaryRows },
  ]
}

// ── Dashboard sub-components ──────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: 'blue' | 'green' | 'amber' | 'red' | 'gray'
}) {
  const colors = {
    blue: 'bg-blue-50 border-blue-200 text-blue-900',
    green: 'bg-green-50 border-green-200 text-green-900',
    amber: 'bg-amber-50 border-amber-200 text-amber-900',
    red: 'bg-red-50 border-red-200 text-red-900',
    gray: 'bg-gray-50 border-gray-200 text-gray-900',
  }
  const cls = colors[accent ?? 'gray']
  return (
    <div className={`border rounded-lg p-4 ${cls}`}>
      <p className="text-xs font-medium opacity-70 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{value}</p>
      {sub && <p className="text-xs mt-0.5 opacity-60">{sub}</p>}
    </div>
  )
}

function NullBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
        <div
          className={`h-full rounded-full ${pctColor(pct)}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-gray-600">{pct.toFixed(1)}%</span>
    </div>
  )
}

function NullAnalysisPanel({ f }: { f: FileProfilingSummary }) {
  const entries = Object.entries(f.null_counts)
  const hasNulls = entries.some(([, c]) => c > 0)
  return (
    <div>
      <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
        Null Analysis
      </h5>
      {!hasNulls ? (
        <div className="flex items-center gap-1.5 text-sm text-green-600">
          <span className="text-green-500">✓</span> No nulls detected
        </div>
      ) : (
        <div className="space-y-1.5">
          {entries.map(([col, count]) => {
            const pct = f.null_percentages[col] ?? 0
            return (
              <div key={col} className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs text-gray-700 w-32 truncate" title={col}>
                  {col}
                </span>
                <NullBar pct={pct} />
                <span className="text-xs text-gray-500 w-12 text-right tabular-nums">
                  {count.toLocaleString()}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function NumericDistPanel({ f }: { f: FileProfilingSummary }) {
  const entries = Object.entries(f.numeric_distributions)
  if (entries.length === 0) return null
  return (
    <div>
      <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
        Numeric Distributions
      </h5>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left py-1.5 pr-3 font-medium text-gray-500">Column</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Min</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Max</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Mean</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Median</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Std Dev</th>
              <th className="text-right py-1.5 pl-2 font-medium text-gray-500">Sum</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {entries.map(([col, d]) => (
              <tr key={col} className="hover:bg-gray-50">
                <td className="py-1.5 pr-3 font-mono text-gray-700">{col}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600">{n(d.min)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600">{n(d.max)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600">{n(d.mean)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600">{n(d.median)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-gray-600">{n(d.std)}</td>
                <td className="py-1.5 pl-2 text-right tabular-nums font-medium text-gray-800">{n(d.sum)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function DateRangePanel({ f }: { f: FileProfilingSummary }) {
  const entries = Object.entries(f.date_ranges)
  if (entries.length === 0) return null
  return (
    <div>
      <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
        Date Ranges
      </h5>
      <div className="flex flex-wrap gap-2">
        {entries.map(([col, dr]) => (
          <div key={col} className="bg-gray-50 border border-gray-200 rounded-md px-3 py-2 text-xs">
            <span className="font-mono font-medium text-gray-700">{col}</span>
            <div className="text-gray-500 mt-0.5">
              {dr.min ?? '—'} <span className="text-gray-300">→</span> {dr.max ?? '—'}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function EntityPanel({ f }: { f: FileProfilingSummary }) {
  const entries = Object.entries(f.entity_distribution).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return null
  const total = entries.reduce((s, [, c]) => s + c, 0)
  const top = entries.slice(0, 8)

  return (
    <div>
      <h5 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
        Entity Distribution{' '}
        <span className="text-gray-400 font-normal normal-case">
          ({entries.length} entities, {total.toLocaleString()} rows)
        </span>
      </h5>
      <div className="space-y-1.5">
        {top.map(([entity, count]) => {
          const pct = (count / total) * 100
          return (
            <div key={entity} className="flex items-center gap-2">
              <span className="font-mono text-xs text-gray-700 w-28 truncate" title={entity}>
                {entity}
              </span>
              <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-400 rounded-full"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs tabular-nums text-gray-500 w-20 text-right">
                {count.toLocaleString()} ({pct.toFixed(1)}%)
              </span>
            </div>
          )
        })}
        {entries.length > 8 && (
          <p className="text-xs text-gray-400">+ {entries.length - 8} more entities</p>
        )}
      </div>
    </div>
  )
}

function FileCard({ fileKey, f }: { fileKey: string; f: FileProfilingSummary }) {
  const [open, setOpen] = useState(true)
  const dupPct = f.row_count > 0 ? (f.duplicate_row_count / f.row_count) * 100 : 0
  const totalNulls = Object.values(f.null_counts).reduce((s, c) => s + c, 0)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Card header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between bg-gray-50 px-4 py-3 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-900">
            {FILE_LABELS[fileKey] ?? fileKey}
          </span>
          <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">
            {f.row_count.toLocaleString()} rows
          </span>
          {f.duplicate_row_count > 0 && (
            <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
              {f.duplicate_row_count} dupes ({dupPct.toFixed(1)}%)
            </span>
          )}
          {totalNulls > 0 && (
            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
              {totalNulls.toLocaleString()} nulls
            </span>
          )}
        </div>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {/* Card body */}
      {open && (
        <div className="p-4 space-y-6">
          <NullAnalysisPanel f={f} />
          <NumericDistPanel f={f} />
          <DateRangePanel f={f} />
          <EntityPanel f={f} />
        </div>
      )}
    </div>
  )
}

function ProfileDashboard({ profile, sessionId }: { profile: ProfilingResponse; sessionId: string }) {
  const cf = profile.metrics.cross_file
  const deltaSign = cf.row_count_delta > 0 ? '+' : ''
  const deltaAccent = Math.abs(cf.row_count_delta_pct) > 10 ? 'amber' : 'gray'
  const profileSheets = useMemo(() => buildProfileSheets(profile, sessionId), [profile, sessionId])

  return (
    <div className="mb-8 space-y-6">
      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Profile Summary</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Snapshot: <span className="font-mono">{profile.snapshot.key}</span>
          </p>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="GL Rows" value={cf.gl_row_count.toLocaleString()} accent="blue" />
        <StatCard label="Subledger Rows" value={cf.subledger_row_count.toLocaleString()} accent="blue" />
        <StatCard
          label="Row Delta"
          value={`${deltaSign}${cf.row_count_delta.toLocaleString()}`}
          sub={`${deltaSign}${cf.row_count_delta_pct.toFixed(1)}% vs subledger`}
          accent={deltaAccent}
        />
        <StatCard
          label="Files"
          value={Object.keys(profile.metrics.files).length}
          sub="validated"
          accent="gray"
        />
      </div>

      {/* Narrative */}
      <div className="bg-blue-50 border border-blue-100 rounded-lg p-4">
        <h4 className="text-xs font-semibold text-blue-700 uppercase tracking-wider mb-2">
          Narrative
        </h4>
        <p className="text-sm text-blue-900 leading-relaxed whitespace-pre-wrap">
          {profile.narrative}
        </p>
      </div>

      {/* Per-file cards */}
      <div className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-900">Per-File Details</h4>
        {Object.entries(profile.metrics.files).map(([key, f]) => (
          <FileCard key={key} fileKey={key} f={f} />
        ))}
      </div>

      <DownloadPanel
        filename={`profile_analytics_${sessionId.slice(0, 8)}`}
        sheets={profileSheets}
      />

      {/* Divider before preprocess action */}
      <div className="border-t border-dashed border-gray-200 pt-6">
        <p className="text-xs text-gray-400 mb-4">
          Review the profile above, then run preprocessing to normalize vendor names.
        </p>
      </div>
    </div>
  )
}

// ── Normalization table ───────────────────────────────────────────────────────

type SortKey = keyof NormalizationEntry
type SortDir = 'asc' | 'desc'

function NormalizationTable({ entries }: { entries: NormalizationEntry[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('original_vendor')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [filter, setFilter] = useState('')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('asc') }
  }

  const filtered = entries.filter(
    (e) =>
      e.original_vendor.toLowerCase().includes(filter.toLowerCase()) ||
      e.normalized_vendor.toLowerCase().includes(filter.toLowerCase()) ||
      (e.matched_to ?? '').toLowerCase().includes(filter.toLowerCase()),
  )

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] ?? ''
    const bv = b[sortKey] ?? ''
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  const Th = ({ k, label }: { k: SortKey; label: string }) => (
    <th
      onClick={() => handleSort(k)}
      className="text-left py-2 px-3 text-xs font-medium text-gray-600 cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap"
    >
      {label}{sortKey === k ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  )

  const tierColor: Record<string, string> = {
    tier1: 'bg-green-100 text-green-700',
    tier2: 'bg-blue-100 text-blue-700',
    tier3: 'bg-purple-100 text-purple-700',
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-3">
        <input
          type="text"
          placeholder="Filter vendors…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border border-gray-200 rounded-md px-3 py-1.5 text-sm w-full max-w-xs focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <span className="text-xs text-gray-400 flex-shrink-0">
          {sorted.length} / {entries.length}
        </span>
      </div>
      <div className="overflow-x-auto border border-gray-200 rounded-md">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <Th k="original_vendor" label="Original Vendor" />
              <Th k="normalized_vendor" label="Normalized" />
              <Th k="matched_to" label="Matched To" />
              <Th k="match_source" label="Tier" />
              <Th k="similarity_score" label="Similarity" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((entry, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="py-2 px-3 font-mono text-xs text-gray-800">{entry.original_vendor}</td>
                <td className="py-2 px-3 font-mono text-xs text-gray-700">{entry.normalized_vendor}</td>
                <td className="py-2 px-3 font-mono text-xs text-gray-500">
                  {entry.matched_to ?? <span className="text-gray-300">—</span>}
                </td>
                <td className="py-2 px-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${tierColor[entry.match_source] ?? 'bg-gray-100 text-gray-600'}`}>
                    {entry.match_source}
                  </span>
                </td>
                <td className="py-2 px-3 text-xs text-gray-600 tabular-nums">
                  {entry.similarity_score != null
                    ? `${(entry.similarity_score * 100).toFixed(1)}%`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NormalizationResult({ data }: { data: PreprocessingResponse }) {
  const s = data.normalization_summary
  const vendorSheets = useMemo(() => buildVendorMapSheets(data), [data])
  const tierData = [
    { label: 'Tier 1', count: s.tier1_count, color: 'bg-green-100 text-green-700', desc: 'Alias / rules' },
    { label: 'Tier 2', count: s.tier2_count, color: 'bg-blue-100 text-blue-700', desc: 'NLP fuzzy' },
    { label: 'Tier 3', count: s.tier3_count, color: 'bg-purple-100 text-purple-700', desc: 'AI stub' },
  ]

  return (
    <div className="mt-6 space-y-5">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div className="col-span-2 sm:col-span-3 grid grid-cols-3 gap-3">
          {tierData.map((t) => (
            <div key={t.label} className={`${t.color} rounded-lg p-3 text-center`}>
              <p className="text-xs font-medium opacity-70">{t.label}</p>
              <p className="text-2xl font-bold">{t.count}</p>
              <p className="text-xs opacity-60">{t.desc}</p>
            </div>
          ))}
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-500">Total GL Vendors</p>
          <p className="text-xl font-bold text-gray-900">{s.total_unique_gl_vendors}</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-500">Threshold</p>
          <p className="text-xl font-bold text-gray-900">{(s.threshold_used * 100).toFixed(0)}%</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-500">Alias Version</p>
          <p className="text-sm font-bold text-gray-900 mt-1">{s.alias_version}</p>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-3">
          Vendor Normalization Map{' '}
          <span className="font-normal text-gray-400 text-xs">
            ({data.vendor_normalization_map.length} entries)
          </span>
        </h4>
        <NormalizationTable entries={data.vendor_normalization_map} />
      </div>

      <DownloadPanel
        filename={`vendor_normalization_${data.snapshot.key}`}
        sheets={vendorSheets}
      />

      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Preprocessing complete. State: <strong>{data.state}</strong>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PreprocessStep({ sessionId, onSuccess }: Props) {
  // Read cached profile result written by ProfileStep
  const profile = useState<ProfilingResponse | null>(() => {
    const raw = sessionStorage.getItem(`profile_result_${sessionId}`)
    return raw ? (JSON.parse(raw) as ProfilingResponse) : null
  })[0]

  const mutation = useMutation({
    mutationFn: () => runPreprocess(sessionId),
    onSuccess: (data) => {
      const key = `preprocess_result_${sessionId}`
      try {
        sessionStorage.setItem(key, JSON.stringify(data))
      } catch {
        try {
          // Slim: strip the vendor normalization map (can be large with many vendors)
          sessionStorage.setItem(key, JSON.stringify({ ...data, vendor_normalization_map: [] }))
        } catch {
          // Skip caching entirely
        }
      }
      onSuccess()
    },
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      {/* Analytics dashboard from the previous Profile step */}
      {profile ? (
        <ProfileDashboard profile={profile} sessionId={sessionId} />
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-sm text-gray-500 mb-6">
          Profile analytics not available in this view (run the Profile step in this browser session
          to see the dashboard here).
        </div>
      )}

      {/* Preprocess action */}
      <h2 className="text-base font-semibold text-gray-900 mb-1">
        Preprocess — Vendor Normalization
      </h2>
      <p className="text-sm text-gray-500 mb-4">
        Run the 3-tier normalization pipeline (alias map → NLP fuzzy → AI stub) to produce
        consistent vendor keys for downstream matching.
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
        {mutation.isPending ? 'Preprocessing…' : 'Run Preprocessing'}
      </button>

      {mutation.data && <NormalizationResult data={mutation.data} />}
    </div>
  )
}
