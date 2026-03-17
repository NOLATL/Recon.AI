import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef, ColGroupDef, ValueFormatterParams } from 'ag-grid-community'
import { runConsolidate, getConsolidationResult } from '@/api/endpoints'
import type { FinalConsolidationResponse, ReconciliationState } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

interface Props {
  sessionId: string
  state: ReconciliationState
  onSuccess: () => void
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtUsd(v: number): string {
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

// ── Layer colour map ──────────────────────────────────────────────────────────

const LAYER_COLOR: Record<string, string> = {
  deterministic: 'bg-emerald-500/15 text-emerald-300',
  probabilistic: 'bg-bdo-red/15 text-bdo-red-light',
  ai:            'bg-violet-500/15 text-violet-300',
  rejected:      'bg-bdo-red/15 text-bdo-red-light',
}

// ── Download sheet builders ───────────────────────────────────────────────────

function buildConsolidationSheets(data: FinalConsolidationResponse): PanelSheet[] {
  const s = data.summary
  const total = s.total_match_count

  const summaryRows: Record<string, unknown>[] = [
    { Category: 'Matches',  Metric: 'Total Matches',   Value: total },
    { Category: 'Matches',  Metric: 'Deterministic',   Value: s.deterministic_match_count,
      '%': total > 0 ? `${((s.deterministic_match_count / total) * 100).toFixed(1)}%` : '' },
    { Category: 'Matches',  Metric: 'Probabilistic',   Value: s.probabilistic_match_count,
      '%': total > 0 ? `${((s.probabilistic_match_count / total) * 100).toFixed(1)}%` : '' },
    { Category: 'Matches',  Metric: 'AI',              Value: s.ai_match_count,
      '%': total > 0 ? `${((s.ai_match_count / total) * 100).toFixed(1)}%` : '' },
    { Category: 'Residual', Metric: 'GL Residual',     Value: s.residual_gl_count },
    { Category: 'Residual', Metric: 'Sub Residual',    Value: s.residual_sub_count },
    { Category: 'Outcomes', Metric: 'Rejected',        Value: s.rejected_count },
    { Category: 'Outcomes', Metric: 'Overrides',       Value: s.override_count },
    { Category: 'Meta',     Metric: 'Session ID',      Value: data.session_id },
    { Category: 'Meta',     Metric: 'State',           Value: data.state },
    { Category: 'Meta',     Metric: 'Snapshot Key',    Value: data.snapshot.key },
  ]

  const matchRows = data.final_matches.map((m) => ({
    'Layer':      m['layer'],
    'Match ID':   m['match_id'],
    'Grouping':   m['grouping_type'],
    'Confidence': m['confidence_score'] ?? m['ai_confidence_score'],
    'GL IDs':     Array.isArray(m['record_ids_A']) ? (m['record_ids_A'] as string[]).join(', ') : '',
    'Sub IDs':    Array.isArray(m['record_ids_B']) ? (m['record_ids_B'] as string[]).join(', ') : '',
    'Status':     m['user_status'],
  }))

  const rejectedRows = data.rejected_matches.map((m) => ({
    'Match ID':   m['match_id'],
    'Grouping':   m['grouping_type'],
    'GL IDs':     Array.isArray(m['record_ids_A']) ? (m['record_ids_A'] as string[]).join(', ') : '',
    'Sub IDs':    Array.isArray(m['record_ids_B']) ? (m['record_ids_B'] as string[]).join(', ') : '',
    'Status':     m['user_status'],
  }))

  return [
    { id: 'summary',      label: 'Summary',                                     name: 'Summary',      rows: summaryRows },
    { id: 'matches',      label: `Final Matches (${data.final_matches.length})`, name: 'Matches',      rows: matchRows },
    { id: 'gl_residual',  label: `GL Residual (${data.residual_gl_records.length})`, name: 'GL Residual', rows: data.residual_gl_records as Record<string, unknown>[] },
    { id: 'sub_residual', label: `Sub Residual (${data.residual_sub_records.length})`, name: 'Sub Residual', rows: data.residual_sub_records as Record<string, unknown>[] },
    { id: 'rejected',     label: `Rejected (${data.rejected_matches.length})`,  name: 'Rejected',     rows: rejectedRows },
  ]
}

// ── BANS Analysis ─────────────────────────────────────────────────────────────

function BansSection({ data }: { data: FinalConsolidationResponse }) {
  const s = data.summary
  const total = s.total_match_count

  // B — Big groups (matches with >1 record on either side)
  const bigGroups = useMemo(
    () => data.final_matches.filter(
      (m) => (m['record_ids_A'] as string[]).length + (m['record_ids_B'] as string[]).length > 2,
    ),
    [data.final_matches],
  )

  // A — amount proxy: count per layer
  const detPct  = total > 0 ? (s.deterministic_match_count  / total) * 100 : 0
  const probPct = total > 0 ? (s.probabilistic_match_count / total) * 100 : 0
  const aiPct   = total > 0 ? (s.ai_match_count             / total) * 100 : 0

  // N — notable residuals
  const totalGl  = s.deterministic_match_count + s.probabilistic_match_count +
                   s.ai_match_count + s.residual_gl_count   // rough estimate
  const totalSub = s.deterministic_match_count + s.probabilistic_match_count +
                   s.ai_match_count + s.residual_sub_count
  const glResiPct  = totalGl  > 0 ? (s.residual_gl_count  / totalGl)  * 100 : 0
  const subResiPct = totalSub > 0 ? (s.residual_sub_count / totalSub) * 100 : 0

  // S — source sensitivity: what % came from lower-confidence layers
  const lowerConfPct = probPct + aiPct

  return (
    <div>
      <h4 className="text-sm font-semibold text-white mb-1">BANS Analysis</h4>
      <p className="text-xs text-white/50 mb-4">
        Big groups · Amount mix · Notable residuals · Source sensitivity
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

        {/* B — Big Groups */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            B — Big Groups
          </p>
          <p className="text-2xl font-bold text-white tabular-nums">{bigGroups.length}</p>
          <p className="text-xs text-white/50 mb-3">N:1 / 1:N multi-record matches</p>
          {bigGroups.length > 0 ? (
            <>
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-void-border/50">
                    <th className="text-left py-1 pr-2 font-medium text-white/50">Match ID</th>
                    <th className="text-center py-1 px-2 font-medium text-white/50">GL</th>
                    <th className="text-center py-1 px-2 font-medium text-white/50">Sub</th>
                    <th className="text-left py-1 pl-2 font-medium text-white/50">Layer</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-void-border/30">
                  {bigGroups.slice(0, 6).map((m, i) => (
                    <tr key={i}>
                      <td className="py-1 pr-2 font-mono text-white/75 truncate max-w-[120px]">
                        {String(m['match_id'] ?? '')}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-white">
                        {(m['record_ids_A'] as string[]).length}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-white">
                        {(m['record_ids_B'] as string[]).length}
                      </td>
                      <td className="py-1 pl-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${LAYER_COLOR[String(m['layer'] ?? '')] ?? 'bg-void-border text-white/50'}`}>
                          {String(m['layer'] ?? '')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {bigGroups.length > 6 && (
                <p className="text-[10px] text-white/35 mt-1.5">
                  +{bigGroups.length - 6} more — see Matches grid below
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-emerald-400">All matches are 1:1 — no complex groupings.</p>
          )}
        </div>

        {/* A — Amount Mix by Layer */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            A — Amount Mix by Layer
          </p>
          <div className="space-y-2.5">
            {[
              { label: 'Deterministic', count: s.deterministic_match_count, pct: detPct,  color: 'bg-emerald-400' },
              { label: 'Probabilistic', count: s.probabilistic_match_count, pct: probPct, color: 'bg-bdo-red/60' },
              { label: 'AI',            count: s.ai_match_count,            pct: aiPct,   color: 'bg-violet-400' },
            ].map(({ label, count, pct, color }) => (
              <div key={label}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-white/60">{label}</span>
                  <span className="font-medium tabular-nums">
                    {count.toLocaleString()} ({pct.toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-void-border rounded-full h-1.5">
                  <div
                    className={`h-1.5 rounded-full ${color}`}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className={`mt-3 p-2 rounded text-[11px] ${
            lowerConfPct < 5 ? 'bg-emerald-500/10 text-emerald-300' :
            lowerConfPct < 20 ? 'bg-amber-500/10 text-amber-300' : 'bg-bdo-red/10 text-bdo-red-light'
          }`}>
            {lowerConfPct.toFixed(1)}% of matches came from probabilistic or AI layers — review
            {lowerConfPct >= 20 ? ' carefully' : ' as needed'}.
          </div>
        </div>

        {/* N — Notable Residuals */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            N — Notable Residuals
          </p>
          <div className="space-y-4">
            {[
              { label: 'GL Residual',  count: s.residual_gl_count,  pct: glResiPct },
              { label: 'Sub Residual', count: s.residual_sub_count, pct: subResiPct },
            ].map(({ label, count, pct }) => (
              <div key={label}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-white/50">{label}</span>
                  <span className={`font-semibold ${
                    pct < 10 ? 'text-emerald-400' : pct < 30 ? 'text-amber-300' : 'text-bdo-red-light'
                  }`}>
                    {count.toLocaleString()} ({pct.toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-void-border rounded-full h-2">
                  <div
                    className={`h-2 rounded-full ${
                      pct < 10 ? 'bg-emerald-400' : pct < 30 ? 'bg-amber-400' : 'bg-bdo-red/80'
                    }`}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-white/35 mt-3">
            {s.rejected_count} match{s.rejected_count !== 1 ? 'es' : ''} rejected across all phases.
          </p>
        </div>

        {/* S — Source Sensitivity */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            S — Source Sensitivity
          </p>
          <div className="space-y-2">
            {[
              { label: 'Deterministic (authoritative)', count: s.deterministic_match_count, risk: false },
              { label: 'Probabilistic (additive)',       count: s.probabilistic_match_count, risk: probPct > 10 },
              { label: 'AI (advisory)',                  count: s.ai_match_count,            risk: aiPct > 5 },
              { label: 'Rejected (all phases)',          count: s.rejected_count,            risk: false },
            ].map(({ label, count, risk }) => (
              <div key={label} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-white/60 flex-1 truncate">{label}</span>
                <span className={`font-bold tabular-nums flex-shrink-0 ${
                  risk && count > 0 ? 'text-amber-300' : 'text-white'
                }`}>
                  {count.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
          {s.override_count > 0 && (
            <div className="mt-3 p-2 bg-amber-500/10 rounded text-[11px] text-amber-300">
              {s.override_count} override flag{s.override_count !== 1 ? 's' : ''} set — manual review recommended.
            </div>
          )}
          {s.override_count === 0 && (
            <div className="mt-3 p-2 bg-emerald-500/10 rounded text-[11px] text-emerald-300">
              No overrides — all matches accepted through standard review workflow.
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

// ── AG Grid — enriched final matches ─────────────────────────────────────────

function buildEnrichedFinalData(
  matches: Record<string, unknown>[],
  glRecords: Record<string, unknown>[],
  subRecords: Record<string, unknown>[],
): { rows: Record<string, unknown>[]; colDefs: (ColDef | ColGroupDef)[] } {
  const glMap = new Map<string, Record<string, unknown>>()
  glRecords.forEach((r) => {
    const id = String(r['gl_id'] ?? '')
    if (id) glMap.set(id, r)
  })
  const subMap = new Map<string, Record<string, unknown>>()
  subRecords.forEach((r) => {
    const id = String(r['subledger_id'] ?? '')
    if (id) subMap.set(id, r)
  })

  const glCols  = glRecords.length  > 0 ? Object.keys(glRecords[0])  : []
  const subCols = subRecords.length > 0 ? Object.keys(subRecords[0]) : []

  const rows = matches.map((m) => {
    const glIds  = (m['record_ids_A'] as string[] | undefined) ?? []
    const subIds = (m['record_ids_B'] as string[] | undefined) ?? []
    const glRecs  = glIds.map((id)  => glMap.get(id)).filter(Boolean)  as Record<string, unknown>[]
    const subRecs = subIds.map((id) => subMap.get(id)).filter(Boolean) as Record<string, unknown>[]

    const row: Record<string, unknown> = {
      layer:                m['layer'],
      match_id:             m['match_id'],
      grouping_type:        m['grouping_type'],
      confidence_score:     m['confidence_score'] ?? m['ai_confidence_score'],
    }
    glCols.forEach((col)  => { row[`gl__${col}`]  = glRecs.map((r)  => String(r[col]  ?? '')).join(' | ') })
    subCols.forEach((col) => { row[`sub__${col}`] = subRecs.map((r) => String(r[col] ?? '')).join(' | ') })
    return row
  })

  function makeChildColDefs(cols: string[], prefix: string): ColDef[] {
    return cols.map((col) => ({
      field: `${prefix}${col}`,
      headerName: col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      filter: true,
      sortable: true,
      resizable: true,
      width: col.endsWith('_id') ? 160 : col === 'amount' ? 120 :
             col === 'transaction_date' ? 130 : col.toLowerCase().includes('vendor') ? 180 : 135,
      cellStyle: col.endsWith('_id') ? { fontFamily: 'monospace', fontSize: '11px' } : undefined,
    }))
  }

  const matchChildren: ColDef[] = [
    {
      field: 'layer',
      headerName: 'Layer',
      width: 120,
      filter: true,
      pinned: 'left',
      cellStyle: (p) => {
        const styles: Record<string, { color: string; fontWeight: string }> = {
          deterministic: { color: '#166534', fontWeight: '600' },
          probabilistic: { color: '#1e40af', fontWeight: '600' },
          ai:            { color: '#6b21a8', fontWeight: '600' },
        }
        return styles[String(p.value)] ?? {}
      },
    },
    {
      field: 'match_id',
      headerName: 'Match ID',
      width: 210,
      filter: true,
      pinned: 'left',
      cellStyle: { fontFamily: 'monospace', fontSize: '11px' },
    },
    { field: 'grouping_type', headerName: 'Grouping', width: 110, filter: true },
    {
      field: 'confidence_score',
      headerName: 'Conf.',
      width: 85,
      type: 'numericColumn',
      filter: true,
      valueFormatter: (p: ValueFormatterParams) =>
        p.value != null ? `${(Number(p.value) * 100).toFixed(0)}%` : '—',
      cellStyle: (p) => {
        const v = Number(p.value)
        return { color: v >= 0.95 ? '#16a34a' : v >= 0.75 ? '#2563eb' : '#d97706', fontWeight: '600' }
      },
    },
  ]

  const colDefs: (ColDef | ColGroupDef)[] = [
    { headerName: 'Match',          children: matchChildren },
    { headerName: 'General Ledger', children: makeChildColDefs(glCols,  'gl__') },
    { headerName: 'Subledger',      children: makeChildColDefs(subCols, 'sub__') },
  ]

  return { rows, colDefs }
}

interface MatchGridProps {
  matches: Record<string, unknown>[]
  glRecords: Record<string, unknown>[]
  subRecords: Record<string, unknown>[]
}

function FinalMatchesGrid({ matches, glRecords, subRecords }: MatchGridProps) {
  const { rows, colDefs } = useMemo(
    () => buildEnrichedFinalData(matches, glRecords, subRecords),
    [matches, glRecords, subRecords],
  )
  return (
    <div className="ag-theme-alpine w-full" style={{ height: 520 }}>
      <AgGridReact
        rowData={rows}
        columnDefs={colDefs}
        defaultColDef={{ sortable: true, resizable: true, filter: true }}
        pagination
        paginationPageSize={25}
        rowHeight={32}
        headerHeight={36}
        groupHeaderHeight={36}
        enableCellTextSelection
        tooltipShowDelay={300}
      />
    </div>
  )
}

// ── AG Grid — residual / rejected DataFrames ──────────────────────────────────

function buildDfColDefs(rows: Record<string, unknown>[]): ColDef[] {
  if (rows.length === 0) return []
  return Object.keys(rows[0]).map((key) => {
    const isId     = key.endsWith('_id')
    const isAmount = key === 'amount'
    const isDate   = key === 'transaction_date'
    const isVendor = key.toLowerCase().includes('vendor')
    return {
      field: key,
      headerName: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      sortable: true,
      resizable: true,
      filter: true,
      width: isId ? 180 : isAmount ? 130 : isDate ? 130 : isVendor ? 200 : 140,
      cellStyle: isId ? { fontFamily: 'monospace', fontSize: '11px' } : undefined,
      type: isAmount ? 'numericColumn' : undefined,
      valueFormatter: isAmount
        ? (p: ValueFormatterParams) =>
            p.value != null
              ? Number(p.value).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
              : ''
        : undefined,
    }
  })
}

function DataFrameGrid({ rows, label, badge, badgeColor = 'bg-bdo-red/15 text-bdo-red-light' }: {
  rows: Record<string, unknown>[]
  label: string
  badge?: string
  badgeColor?: string
}) {
  const colDefs = useMemo(() => buildDfColDefs(rows), [rows])
  if (rows.length === 0) {
    return (
      <div className="border border-void-border rounded-xl p-5 text-center bg-void-elevated">
        <p className="text-sm text-white/50">{label} — 0 rows</p>
      </div>
    )
  }
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium text-white/70">{label}</span>
        {badge && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${badgeColor}`}>
            {badge}
          </span>
        )}
        <span className="text-xs text-white/35 ml-auto">Sort · filter · resize any column</span>
      </div>
      <div className="ag-theme-alpine w-full" style={{ height: 420 }}>
        <AgGridReact
          rowData={rows}
          columnDefs={colDefs}
          defaultColDef={{ sortable: true, resizable: true, filter: true }}
          pagination
          paginationPageSize={20}
          rowHeight={32}
          headerHeight={36}
          enableCellTextSelection
        />
      </div>
    </div>
  )
}

// ── Residual tabs ─────────────────────────────────────────────────────────────

type ResidualTab = 'gl_residual' | 'sub_residual'

function ResidualTabs({ data }: { data: FinalConsolidationResponse }) {
  const [active, setActive] = useState<ResidualTab>('gl_residual')

  const tabs: { id: ResidualTab; label: string; rows: Record<string, unknown>[]; badge: string }[] = [
    { id: 'gl_residual',  label: 'GL Residual (unmatched)',  rows: data.residual_gl_records,  badge: 'bg-amber-500/15 text-amber-300' },
    { id: 'sub_residual', label: 'Sub Residual (unmatched)', rows: data.residual_sub_records, badge: 'bg-amber-500/15 text-amber-300' },
  ]

  const activeCfg = tabs.find((t) => t.id === active)!

  return (
    <div>
      <div className="flex gap-1 border-b border-void-border mb-4 overflow-x-auto">
        {tabs.map((tab) => {
          const isActive = tab.id === active
          return (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
                isActive
                  ? 'border-bdo-red text-bdo-red-light font-medium'
                  : 'border-transparent text-white/40 hover:text-white/70 hover:border-void-border'
              }`}
            >
              {tab.label}
              <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                isActive ? tab.badge : 'bg-void-border text-white/50'
              }`}>
                {tab.rows.length}
              </span>
            </button>
          )
        })}
      </div>
      <DataFrameGrid
        rows={activeCfg.rows}
        label={activeCfg.label}
        badge={`${activeCfg.rows.length} rows`}
        badgeColor={activeCfg.badge}
      />
    </div>
  )
}

// ── Full analytics panel ──────────────────────────────────────────────────────

function ConsolidationAnalytics({ data }: { data: FinalConsolidationResponse }) {
  const s = data.summary
  const total = s.total_match_count
  const consolidationSheets = useMemo(() => buildConsolidationSheets(data), [data])

  return (
    <div className="mb-8 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-white">Final Consolidation — Results</h3>
        <p className="text-xs text-white/50 mt-0.5">
          {total.toLocaleString()} total matches across all layers ·
          snapshot <span className="font-mono">{data.snapshot.key}</span>
        </p>
      </div>

      {/* KPI row — matches by layer */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Matches',  value: total,                        sub: '',                          accent: 'blue' },
          { label: 'Deterministic',  value: s.deterministic_match_count,  sub: total > 0 ? `${((s.deterministic_match_count  / total) * 100).toFixed(1)}%` : '', accent: 'green' },
          { label: 'Probabilistic',  value: s.probabilistic_match_count,  sub: total > 0 ? `${((s.probabilistic_match_count / total) * 100).toFixed(1)}%` : '', accent: 'blue' },
          { label: 'AI',             value: s.ai_match_count,             sub: total > 0 ? `${((s.ai_match_count             / total) * 100).toFixed(1)}%` : '', accent: 'purple' },
        ].map(({ label, value, sub, accent }) => {
          const cls = {
            blue:   'bg-bdo-red/8 border-bdo-red/20 text-white',
            green:  'bg-emerald-500/8 border-emerald-500/20 text-white',
            purple: 'bg-violet-500/10 border-violet-500/20 text-white',
          }[accent]
          return (
            <div key={label} className={`border rounded-lg p-4 ${cls}`}>
              <p className="text-xs font-medium opacity-60 uppercase tracking-wide">{label}</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{value.toLocaleString()}</p>
              {sub && <p className="text-xs mt-0.5 opacity-60">{sub} of total</p>}
            </div>
          )
        })}
      </div>

      {/* KPI row — residuals + rejected */}
      <div className="grid grid-cols-3 gap-3">
        <div className="border border-amber-500/20 bg-amber-500/8 rounded-lg p-4">
          <p className="text-xs font-medium text-amber-300 uppercase tracking-wide">GL Residual</p>
          <p className="text-2xl font-bold text-amber-300 tabular-nums mt-1">
            {s.residual_gl_count.toLocaleString()}
          </p>
          <p className="text-xs text-amber-300 mt-0.5">unmatched GL records</p>
        </div>
        <div className="border border-amber-500/20 bg-amber-500/8 rounded-lg p-4">
          <p className="text-xs font-medium text-amber-300 uppercase tracking-wide">Sub Residual</p>
          <p className="text-2xl font-bold text-amber-300 tabular-nums mt-1">
            {s.residual_sub_count.toLocaleString()}
          </p>
          <p className="text-xs text-amber-300 mt-0.5">unmatched Sub records</p>
        </div>
        <div className="border border-bdo-red/20 bg-bdo-red/8 rounded-lg p-4">
          <p className="text-xs font-medium text-bdo-red-light uppercase tracking-wide">Rejected</p>
          <p className="text-2xl font-bold text-bdo-red-light tabular-nums mt-1">
            {s.rejected_count.toLocaleString()}
          </p>
          <p className="text-xs text-bdo-red-light mt-0.5">across all phases</p>
        </div>
      </div>

      {/* BANS */}
      <BansSection data={data} />

      {/* Final Matches — AG Grid */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-white">
            Final Matches{' '}
            <span className="font-normal text-white/35 text-xs">
              ({data.final_matches.length.toLocaleString()} rows)
            </span>
          </h4>
          <p className="text-xs text-white/35">Sort · filter · resize any column</p>
        </div>
        {data.gl_records.length === 0 && data.final_matches.length > 0 && (
          <p className="text-xs text-amber-300 mb-2">
            Record detail columns unavailable — re-run consolidation in this session to populate.
          </p>
        )}
        <FinalMatchesGrid
          matches={data.final_matches}
          glRecords={data.gl_records}
          subRecords={data.sub_records}
        />
      </div>

      {/* Residual tabs */}
      <div>
        <h4 className="text-sm font-semibold text-white mb-1">Residual Records</h4>
        <p className="text-xs text-white/50 mb-4">
          Records that could not be matched across any of the three reconciliation layers.
        </p>
        <ResidualTabs data={data} />
      </div>

      <DownloadPanel
        filename={`consolidation_${data.session_id.slice(0, 8)}`}
        sheets={consolidationSheets}
      />

      <div className="border-t border-dashed border-void-border pt-4">
        <p className="text-xs text-white/35">
          Review the results above, then proceed to Export to generate all output files.
        </p>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const CACHE_KEY = (id: string) => `consolidation_result_${id}`

// States where consolidation has already been completed
const POST_CONSOLIDATION_STATES: ReconciliationState[] = ['final_consolidated', 'finalized']

export default function ConsolidateStep({ sessionId, state, onSuccess }: Props) {
  const isPastConsolidation = POST_CONSOLIDATION_STATES.includes(state)

  // Load from sessionStorage on mount
  const [cached, setCached] = useState<FinalConsolidationResponse | null>(() => {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY(sessionId))
      return raw ? (JSON.parse(raw) as FinalConsolidationResponse) : null
    } catch {
      return null
    }
  })

  // Auto-fetch when past consolidation and no local cache
  const fetchQuery = useQuery({
    queryKey: ['consolidation-result', sessionId],
    queryFn: () => getConsolidationResult(sessionId),
    enabled: isPastConsolidation && !cached,
    retry: 1,
  })

  // Persist fetched data to sessionStorage + local state
  useEffect(() => {
    if (fetchQuery.data && !cached) {
      const key = CACHE_KEY(sessionId)
      try {
        sessionStorage.setItem(key, JSON.stringify(fetchQuery.data))
      } catch {
        try {
          sessionStorage.setItem(key, JSON.stringify({
            ...fetchQuery.data,
            gl_records: [], sub_records: [],
            residual_gl_records: [], residual_sub_records: [],
          }))
        } catch { /* quota exceeded */ }
      }
      setCached(fetchQuery.data)
    }
  }, [fetchQuery.data, cached, sessionId])

  const mutation = useMutation({
    mutationFn: () => runConsolidate(sessionId),
    onSuccess: (data) => {
      const key = CACHE_KEY(sessionId)
      try {
        sessionStorage.setItem(key, JSON.stringify(data))
      } catch {
        try {
          sessionStorage.setItem(key, JSON.stringify({
            ...data,
            gl_records: [], sub_records: [],
            residual_gl_records: [], residual_sub_records: [],
          }))
        } catch { /* quota exceeded */ }
      }
      setCached(data)
      onSuccess()
    },
  })

  const displayData = mutation.data ?? cached

  return (
    <div className="glass-card p-6">
      {/* Analytics — shown whenever data is available */}
      {displayData && <ConsolidationAnalytics data={displayData} />}

      {/* Loading state for fetch query */}
      {isPastConsolidation && !displayData && fetchQuery.isLoading && (
        <p className="text-sm text-white/50 mb-4">Loading consolidation analytics…</p>
      )}

      {/* Fetch error fallback */}
      {isPastConsolidation && !displayData && fetchQuery.error && (
        <div className="mb-4">
          <ErrorDisplay error={fetchQuery.error} onRefresh={() => fetchQuery.refetch()} />
        </div>
      )}

      {/* Fallback message when no cache and no data (only for non-consolidated states) */}
      {!isPastConsolidation && !displayData && (
        <div className="bg-void-elevated border border-void-border rounded-xl p-3 text-sm text-white/50 mb-6">
          Consolidation analytics not available — run Final Consolidation below to see the full
          breakdown here.
        </div>
      )}

      {/* Consolidation action — only shown when not yet past consolidation */}
      {!isPastConsolidation && (
        <>
          <h2 className="text-base font-semibold text-white mb-1">Final Consolidation</h2>
          <p className="text-sm text-white/50 mb-2">
            Assemble the complete reconciliation dataset from all accepted matches across
            deterministic, probabilistic, and AI layers.
          </p>
          <div className="bg-bdo-red/8 border border-bdo-red/20 rounded-xl p-3 text-sm text-white/70 mb-5">
            This is a pure bookkeeping step — no recomputation occurs. A snapshot is captured
            before the state advances.
          </div>

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
            {mutation.isPending ? 'Consolidating…' : 'Run Final Consolidation'}
          </button>
        </>
      )}
    </div>
  )
}
