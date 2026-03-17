import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef, ColGroupDef, ValueFormatterParams } from 'ag-grid-community'
import { confirmDeterministicReview } from '@/api/endpoints'
import type {
  DeterministicReviewResponse,
  DeterministicResponse,
  MatchRecord,
  ScenarioAmountSummary,
} from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'
// AG Grid 31 Community edition auto-registers the ClientSideRowModel — no manual registration needed.

interface Props {
  sessionId: string
  onSuccess: () => void
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtUsd(v: number): string {
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

// ── Download sheet builders ───────────────────────────────────────────────────

function buildDetReviewSheets(det: DeterministicResponse): PanelSheet[] {
  const s = det.summary
  const summaryRows: Record<string, unknown>[] = [
    { Metric: 'Match Count',        Value: s.match_count },
    { Metric: 'GL Matched',         Value: s.matched_gl_records },
    { Metric: 'Sub Matched',        Value: s.matched_sub_records },
    { Metric: 'GL Residual',        Value: s.unmatched_gl_records },
    { Metric: 'Sub Residual',       Value: s.unmatched_sub_records },
    { Metric: 'Matched GL Amount',  Value: s.total_matched_gl_amount },
    { Metric: 'Matched Sub Amount', Value: s.total_matched_sub_amount },
    ...s.scenario_amount_summaries.map((sa) => ({
      Metric: `Scenario ${sa.scenario_id} — GL Amount`,
      Value: sa.total_gl_amount,
    })),
    ...s.scenario_amount_summaries.map((sa) => ({
      Metric: `Scenario ${sa.scenario_id} — Sub Amount`,
      Value: sa.total_sub_amount,
    })),
  ]
  const matchRows = det.matches.map((m) => ({
    'Match ID':    m.match_id,
    'Scenario':    m.scenario_id,
    'Description': m.scenario_description,
    'Confidence':  m.confidence_score,
    'Grouping':    m.grouping_type,
    'GL IDs':      m.record_ids_A.join(', '),
    'Sub IDs':     m.record_ids_B.join(', '),
    'Status':      m.user_status,
  }))

  // BANS log rows
  const variance = Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount)
  const variancePct =
    s.total_matched_gl_amount > 0 ? (variance / s.total_matched_gl_amount) * 100 : 0
  const multiGroups = det.matches.filter((m) => m.grouping_type !== 'one_to_one')
  const glResiPct = s.total_gl_records > 0 ? (s.unmatched_gl_records / s.total_gl_records) * 100 : 0
  const subResiPct = s.total_sub_records > 0 ? (s.unmatched_sub_records / s.total_sub_records) * 100 : 0
  const bansRows: Record<string, unknown>[] = [
    { Section: 'B — Big Groups', Metric: 'N:1 / 1:N multi-record matches',       Value: multiGroups.length,           Flag: multiGroups.length === 0 ? 'OK' : multiGroups.length <= 5 ? 'WARN' : 'ALERT' },
    { Section: 'B — Big Groups', Metric: 'Largest group (total records)',          Value: multiGroups.length > 0 ? Math.max(...multiGroups.map((m) => m.record_ids_A.length + m.record_ids_B.length)) : 0, Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Matched GL Amount',                      Value: s.total_matched_gl_amount,    Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Matched Sub Amount',                     Value: s.total_matched_sub_amount,   Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Variance |GL − Sub|',                    Value: variance,                     Flag: variance < 0.01 ? 'OK' : variancePct < 0.1 ? 'WARN' : 'ALERT' },
    { Section: 'A — Amount',     Metric: 'Variance %',                             Value: `${variancePct.toFixed(3)}%`, Flag: variance < 0.01 ? 'OK' : variancePct < 0.1 ? 'WARN' : 'ALERT' },
    { Section: 'N — Residuals',  Metric: 'GL Total Rows',                          Value: s.total_gl_records,           Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'GL Residual Rows',                       Value: s.unmatched_gl_records,       Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'GL Residual %',                          Value: `${glResiPct.toFixed(1)}%`,   Flag: glResiPct < 10 ? 'OK' : glResiPct < 30 ? 'WARN' : 'ALERT' },
    { Section: 'N — Residuals',  Metric: 'Sub Total Rows',                         Value: s.total_sub_records,          Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'Sub Residual Rows',                      Value: s.unmatched_sub_records,      Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'Sub Residual %',                         Value: `${subResiPct.toFixed(1)}%`,  Flag: subResiPct < 10 ? 'OK' : subResiPct < 30 ? 'WARN' : 'ALERT' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 1 — Exact (100% conf.)',        Value: s.scenario_counts['1'] ?? 0, Flag: 'OK' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 2 — Vendor+Amt+Date (95%)',     Value: s.scenario_counts['2'] ?? 0, Flag: 'OK' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 3 — Amt+Entity+Date (85%)',     Value: s.scenario_counts['3'] ?? 0, Flag: (s.scenario_counts['3'] ?? 0) === 0 ? 'OK' : 'WARN' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 4 — Group Sum N:1/1:N (75%)',   Value: s.scenario_counts['4'] ?? 0, Flag: (s.scenario_counts['4'] ?? 0) === 0 ? 'OK' : (s.scenario_counts['4'] ?? 0) <= 3 ? 'WARN' : 'ALERT' },
  ]

  return [
    { id: 'summary',      label: 'Summary',                                          name: 'Summary',         rows: summaryRows },
    { id: 'bans',         label: 'BANS Report',                                      name: 'BANS Report',     rows: bansRows },
    { id: 'matches',      label: `Matched Records (${det.matches.length})`,          name: 'Matched Records', rows: matchRows },
    { id: 'gl_input',     label: `GL Input (${det.gl_records.length})`,              name: 'GL Input',        rows: det.gl_records as Record<string, unknown>[] },
    { id: 'sub_input',    label: `Sub Input (${det.sub_records.length})`,            name: 'Sub Input',       rows: det.sub_records as Record<string, unknown>[] },
    { id: 'gl_residual',  label: `GL Residual (${det.residual_gl_records.length})`,  name: 'GL Residual',     rows: det.residual_gl_records as Record<string, unknown>[] },
    { id: 'sub_residual', label: `Sub Residual (${det.residual_sub_records.length})`, name: 'Sub Residual',   rows: det.residual_sub_records as Record<string, unknown>[] },
  ]
}

// ── Scenario metadata ─────────────────────────────────────────────────────────

const SCENARIO_META: Record<
  number,
  { label: string; confidence: string; color: string; dotColor: string; description: string }
> = {
  1: {
    label: 'Scenario 1 — Exact Match',
    confidence: '100%',
    color: 'border-emerald-500/30 bg-emerald-500/5',
    dotColor: 'bg-emerald-500',
    description:
      'All four dimensions match exactly: normalized vendor name, transaction amount (rounded to 2 d.p.), date, and entity. This is the strongest possible deterministic match — no ambiguity remains.',
  },
  2: {
    label: 'Scenario 2 — Vendor + Amount + Date Tolerance',
    confidence: '95%',
    color: 'border-bdo-red/30 bg-bdo-red/5',
    dotColor: 'bg-bdo-red',
    description:
      'Normalized vendor and amount match exactly, with a date tolerance of ±60 days. Handles timing differences caused by accruals, cut-off periods, and processing delays between GL posting and subledger recording.',
  },
  3: {
    label: 'Scenario 3 — Amount + Entity + Date Tolerance',
    confidence: '85%',
    color: 'border-amber-500/30 bg-amber-500/5',
    dotColor: 'bg-amber-400',
    description:
      'Amount and entity match exactly within a ±60-day date window, but vendor names differ. Covers cases where vendor names are recorded inconsistently but the transaction amount and business unit make the pairing unambiguous.',
  },
  4: {
    label: 'Scenario 4 — Group Sum Match (N:1 / 1:N)',
    confidence: '75%',
    color: 'border-violet-500/30 bg-violet-500/5',
    dotColor: 'bg-violet-500',
    description:
      'Many GL records sum to one Subledger record, or one GL record equals a group of Subledger records. Groups are bounded at 5 records and must share the same entity. Handles invoice consolidation, instalment splits, and multi-line journal entries.',
  },
}

// ── Per-scenario stats (merged from matches + amount summaries) ───────────────

interface ScenarioStats {
  id: number
  count: number
  glRecords: number
  subRecords: number
  totalGlAmount: number
  totalSubAmount: number
}

function deriveScenarioStats(
  matches: MatchRecord[],
  amountSummaries: ScenarioAmountSummary[],
): ScenarioStats[] {
  const byScenario: Record<number, MatchRecord[]> = {}
  for (const m of matches) {
    if (!byScenario[m.scenario_id]) byScenario[m.scenario_id] = []
    byScenario[m.scenario_id].push(m)
  }
  const amtMap = Object.fromEntries(amountSummaries.map((s) => [s.scenario_id, s]))
  return Object.entries(byScenario)
    .map(([id, ms]) => {
      const numId = Number(id)
      const amt = amtMap[numId]
      return {
        id: numId,
        count: ms.length,
        glRecords: ms.reduce((s, m) => s + m.record_ids_A.length, 0),
        subRecords: ms.reduce((s, m) => s + m.record_ids_B.length, 0),
        totalGlAmount: amt?.total_gl_amount ?? 0,
        totalSubAmount: amt?.total_sub_amount ?? 0,
      }
    })
    .sort((a, b) => a.id - b.id)
}

// ── Scenario card ─────────────────────────────────────────────────────────────

function ScenarioCard({ stats, totalMatches }: { stats: ScenarioStats; totalMatches: number }) {
  const meta = SCENARIO_META[stats.id]
  if (!meta) return null
  const pct = totalMatches > 0 ? ((stats.count / totalMatches) * 100).toFixed(1) : '0'

  return (
    <div className={`border rounded-lg overflow-hidden ${meta.color}`}>
      <div className="px-4 py-3 flex items-start gap-2">
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 mt-1 ${meta.dotColor}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-sm font-semibold text-white">{meta.label}</span>
            <span className="text-xs font-bold text-white/60 flex-shrink-0">
              {meta.confidence} confidence
            </span>
          </div>
          <p className="text-xs text-white/60 mt-1.5 leading-relaxed">{meta.description}</p>
        </div>
      </div>
      <div className="px-4 pb-4 flex items-center gap-6 border-t border-void-border pt-3 flex-wrap">
        <div>
          <p className="text-2xl font-bold text-white tabular-nums">{stats.count}</p>
          <p className="text-xs text-white/50">
            match{stats.count !== 1 ? 'es' : ''} ({pct}% of total)
          </p>
        </div>
        <div className="h-8 w-px bg-void-border" />
        <div>
          <p className="text-lg font-bold text-white/75 tabular-nums">{stats.glRecords}</p>
          <p className="text-xs text-white/50">GL records</p>
        </div>
        <div>
          <p className="text-lg font-bold text-white/75 tabular-nums">{stats.subRecords}</p>
          <p className="text-xs text-white/50">Sub records</p>
        </div>
        <div className="h-8 w-px bg-void-border" />
        <div>
          <p className="text-lg font-bold text-emerald-400 tabular-nums">
            {fmtUsd(stats.totalGlAmount)}
          </p>
          <p className="text-xs text-white/50">GL amount</p>
        </div>
        <div>
          <p className="text-lg font-bold text-emerald-400 tabular-nums">
            {fmtUsd(stats.totalSubAmount)}
          </p>
          <p className="text-xs text-white/50">Sub amount</p>
        </div>
      </div>
    </div>
  )
}

// ── BANS Analysis ─────────────────────────────────────────────────────────────

function BansSection({ det }: { det: DeterministicResponse }) {
  const s = det.summary
  const variance = Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount)
  const variancePct =
    s.total_matched_gl_amount > 0 ? (variance / s.total_matched_gl_amount) * 100 : 0
  const glResiPct =
    s.total_gl_records > 0 ? (s.unmatched_gl_records / s.total_gl_records) * 100 : 0
  const subResiPct =
    s.total_sub_records > 0 ? (s.unmatched_sub_records / s.total_sub_records) * 100 : 0
  const sc3 = s.scenario_counts['3'] ?? 0
  const sc4 = s.scenario_counts['4'] ?? 0

  const multiGroups = useMemo(
    () =>
      det.matches
        .filter((m) => m.grouping_type !== 'one_to_one')
        .map((m) => ({ ...m, totalRecords: m.record_ids_A.length + m.record_ids_B.length }))
        .sort((a, b) => b.totalRecords - a.totalRecords),
    [det.matches],
  )

  return (
    <div>
      <h4 className="text-sm font-semibold text-white mb-1">BANS Analysis</h4>
      <p className="text-xs text-white/50 mb-4">
        Big groups · Amount anomalies · Notable residuals · Scenario sensitivity
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

        {/* B — Big Groups */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            B — Big Groups
          </p>
          <p className="text-2xl font-bold text-white tabular-nums">{multiGroups.length}</p>
          <p className="text-xs text-white/50 mb-3">N:1 / 1:N multi-record matches</p>
          {multiGroups.length > 0 ? (
            <>
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-void-border/50">
                    <th className="text-left py-1 pr-2 font-medium text-white/50">Match ID</th>
                    <th className="text-center py-1 px-2 font-medium text-white/50">GL</th>
                    <th className="text-center py-1 px-2 font-medium text-white/50">Sub</th>
                    <th className="text-left py-1 pl-2 font-medium text-white/50">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-void-border/30">
                  {multiGroups.slice(0, 6).map((m) => (
                    <tr key={m.match_id}>
                      <td className="py-1 pr-2 font-mono text-white/75 truncate max-w-[120px]">
                        {m.match_id}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-white">
                        {m.record_ids_A.length}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-white">
                        {m.record_ids_B.length}
                      </td>
                      <td className="py-1 pl-2 text-white/60">{m.grouping_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {multiGroups.length > 6 && (
                <p className="text-[10px] text-white/35 mt-1.5">
                  +{multiGroups.length - 6} more — see Matched Records grid below
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-emerald-400">
              All matches are 1:1 — no complex groupings detected.
            </p>
          )}
        </div>

        {/* A — Amount Variance */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            A — Amount Variance
          </p>
          <div className="space-y-2 text-xs">
            {[
              { label: 'Matched GL',  value: fmtUsd(s.total_matched_gl_amount) },
              { label: 'Matched Sub', value: fmtUsd(s.total_matched_sub_amount) },
            ].map(({ label, value }) => (
              <div key={label} className="flex justify-between">
                <span className="text-white/50">{label}</span>
                <span className="font-medium tabular-nums">{value}</span>
              </div>
            ))}
            <div className="border-t border-void-border/50 pt-2 flex justify-between">
              <span className="text-white/50">Variance</span>
              <span
                className={`font-bold tabular-nums ${
                  variance < 0.01 ? 'text-emerald-400' : variancePct < 0.1 ? 'text-amber-300' : 'text-bdo-red-light'
                }`}
              >
                {fmtUsd(variance)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/50">Variance %</span>
              <span
                className={`font-medium ${
                  variance < 0.01 ? 'text-emerald-400' : variancePct < 0.1 ? 'text-amber-300' : 'text-bdo-red-light'
                }`}
              >
                {variancePct.toFixed(3)}%
              </span>
            </div>
          </div>
          <div
            className={`mt-3 p-2 rounded text-[11px] ${
              variance < 0.01
                ? 'bg-emerald-500/10 text-emerald-300'
                : variancePct < 0.1
                  ? 'bg-amber-500/10 text-amber-300'
                  : 'bg-bdo-red/10 text-bdo-red-light'
            }`}
          >
            {variance < 0.01
              ? 'Perfect balance — GL and Sub amounts align exactly.'
              : variancePct < 0.1
                ? 'Minor variance — likely rounding or timing difference.'
                : 'Material variance — investigate before proceeding.'}
          </div>
        </div>

        {/* N — Notable Residuals */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            N — Notable Residuals
          </p>
          <div className="space-y-4">
            {[
              {
                label: 'GL Residual',
                count: s.unmatched_gl_records,
                total: s.total_gl_records,
                pct: glResiPct,
              },
              {
                label: 'Sub Residual',
                count: s.unmatched_sub_records,
                total: s.total_sub_records,
                pct: subResiPct,
              },
            ].map(({ label, count, total, pct }) => (
              <div key={label}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-white/50">{label}</span>
                  <span
                    className={`font-semibold ${
                      pct < 10 ? 'text-emerald-400' : pct < 30 ? 'text-amber-300' : 'text-bdo-red-light'
                    }`}
                  >
                    {count.toLocaleString()} / {total.toLocaleString()} ({pct.toFixed(1)}%)
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
            Residual records advance to the probabilistic matching pool.
          </p>
        </div>

        {/* S — Scenario Sensitivity */}
        <div className="border border-void-border rounded-lg p-4">
          <p className="text-[11px] font-semibold text-white/40 uppercase tracking-wide mb-3">
            S — Scenario Sensitivity
          </p>
          <div className="space-y-2">
            {[
              { label: 'Sc. 1 — Exact (100%)',             key: '1', risk: false },
              { label: 'Sc. 2 — Vendor + Amt + Date (95%)', key: '2', risk: false },
              { label: 'Sc. 3 — Amt + Entity + Date (85%)', key: '3', risk: true },
              { label: 'Sc. 4 — Group Sum N:1/1:N (75%)',  key: '4', risk: true },
            ].map(({ label, key, risk }) => {
              const count = s.scenario_counts[key] ?? 0
              return (
                <div key={key} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-white/60 flex-1 truncate">{label}</span>
                  <span
                    className={`font-bold tabular-nums flex-shrink-0 ${
                      risk && count > 0 ? (key === '4' ? 'text-bdo-red-light' : 'text-amber-300') : 'text-white'
                    }`}
                  >
                    {count}
                  </span>
                </div>
              )
            })}
          </div>
          {(sc3 > 0 || sc4 > 0) ? (
            <div className="mt-3 p-2 bg-amber-500/10 border border-amber-500/20 rounded-xl text-[11px] text-amber-300">
              {sc4 > 0 &&
                `${sc4} group-sum match${sc4 !== 1 ? 'es' : ''} (Sc. 4) use aggregation — verify groupings. `}
              {sc3 > 0 &&
                `${sc3} vendor-mismatch match${sc3 !== 1 ? 'es' : ''} (Sc. 3) skipped name check — review.`}
            </div>
          ) : (
            <div className="mt-3 p-2 bg-emerald-500/10 rounded text-[11px] text-emerald-300">
              All matches used high-confidence scenarios (1 or 2).
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

// ── AG Grid — enriched matched records (GL + Sub columns joined) ──────────────

function buildEnrichedMatchData(
  matches: MatchRecord[],
  glRecords: Record<string, unknown>[],
  subRecords: Record<string, unknown>[],
): { rows: Record<string, unknown>[]; colDefs: (ColDef | ColGroupDef)[] } {
  // Lookup maps
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

  const glCols = glRecords.length > 0 ? Object.keys(glRecords[0]) : []
  const subCols = subRecords.length > 0 ? Object.keys(subRecords[0]) : []

  // Build enriched rows — multi-record values joined with " | "
  const rows = matches.map((m) => {
    const glRecs = m.record_ids_A
      .map((id) => glMap.get(id))
      .filter(Boolean) as Record<string, unknown>[]
    const subRecs = m.record_ids_B
      .map((id) => subMap.get(id))
      .filter(Boolean) as Record<string, unknown>[]

    const row: Record<string, unknown> = {
      match_id:             m.match_id,
      scenario_id:          m.scenario_id,
      scenario_description: m.scenario_description,
      confidence_score:     m.confidence_score,
      grouping_type:        m.grouping_type,
    }
    glCols.forEach((col) => {
      row[`gl__${col}`] = glRecs.map((r) => String(r[col] ?? '')).join(' | ')
    })
    subCols.forEach((col) => {
      row[`sub__${col}`] = subRecs.map((r) => String(r[col] ?? '')).join(' | ')
    })
    return row
  })

  // Helper: build child ColDefs for a set of record columns
  function makeChildColDefs(cols: string[], prefix: string): ColDef[] {
    return cols.map((col) => ({
      field: `${prefix}${col}`,
      headerName: col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      filter: true,
      sortable: true,
      resizable: true,
      width: col.endsWith('_id')
        ? 160
        : col === 'amount'
          ? 120
          : col === 'transaction_date'
            ? 130
            : col.toLowerCase().includes('vendor')
              ? 180
              : 135,
      cellStyle: col.endsWith('_id') ? { fontFamily: 'monospace', fontSize: '11px' } : undefined,
    }))
  }

  const matchChildren: ColDef[] = [
    {
      field: 'match_id',
      headerName: 'Match ID',
      width: 210,
      filter: true,
      pinned: 'left',
      cellStyle: { fontFamily: 'monospace', fontSize: '11px' },
    },
    { field: 'scenario_id', headerName: 'S#', width: 55, filter: true, type: 'numericColumn' },
    {
      field: 'scenario_description',
      headerName: 'Scenario',
      minWidth: 180,
      flex: 1,
      filter: true,
      tooltipField: 'scenario_description',
    },
    {
      field: 'confidence_score',
      headerName: 'Conf.',
      width: 85,
      type: 'numericColumn',
      filter: true,
      valueFormatter: (p: ValueFormatterParams) =>
        p.value != null ? `${(p.value * 100).toFixed(0)}%` : '',
      cellStyle: (p) => {
        const v = p.value as number
        return { color: v >= 0.95 ? '#16a34a' : v >= 0.85 ? '#2563eb' : '#d97706', fontWeight: '600' }
      },
    },
    { field: 'grouping_type', headerName: 'Grouping', width: 105, filter: true },
  ]

  const colDefs: (ColDef | ColGroupDef)[] = [
    { headerName: 'Match',           children: matchChildren },
    { headerName: 'General Ledger',  children: makeChildColDefs(glCols, 'gl__') },
    { headerName: 'Subledger',       children: makeChildColDefs(subCols, 'sub__') },
  ]

  return { rows, colDefs }
}

interface EnrichedMatchGridProps {
  matches: MatchRecord[]
  glRecords: Record<string, unknown>[]
  subRecords: Record<string, unknown>[]
}

function MatchedRecordsGrid({ matches, glRecords, subRecords }: EnrichedMatchGridProps) {
  const { rows, colDefs } = useMemo(
    () => buildEnrichedMatchData(matches, glRecords, subRecords),
    [matches, glRecords, subRecords],
  )
  return (
    <div className="ag-theme-alpine w-full" style={{ height: 500 }}>
      <AgGridReact
        rowData={rows}
        columnDefs={colDefs}
        defaultColDef={{ sortable: true, resizable: true, filter: true }}
        pagination
        paginationPageSize={20}
        rowHeight={32}
        headerHeight={36}
        groupHeaderHeight={36}
        enableCellTextSelection
        tooltipShowDelay={300}
      />
    </div>
  )
}

// ── AG Grid — GL / Sub / Residual DataFrames ──────────────────────────────────

/** Build AG Grid ColDefs dynamically from the keys of the first row. */
function buildDfColDefs(rows: Record<string, unknown>[]): ColDef[] {
  if (rows.length === 0) return []
  return Object.keys(rows[0]).map((key) => {
    const isAmount = key === 'amount'
    const isDate = key === 'transaction_date'
    const isId = key.endsWith('_id')
    const isVendor = key.toLowerCase().includes('vendor')
    return {
      field: key,
      headerName: key
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase()),
      sortable: true,
      resizable: true,
      filter: true,
      width: isId ? 180 : isAmount ? 130 : isDate ? 130 : isVendor ? 200 : 140,
      cellStyle: isId ? { fontFamily: 'monospace', fontSize: '11px' } : undefined,
      type: isAmount ? 'numericColumn' : undefined,
      valueFormatter: isAmount
        ? (p: ValueFormatterParams) =>
            p.value != null
              ? Number(p.value).toLocaleString('en-US', {
                  style: 'currency',
                  currency: 'USD',
                  maximumFractionDigits: 2,
                })
              : ''
        : undefined,
    }
  })
}

interface DataFrameGridProps {
  rows: Record<string, unknown>[]
  label: string
  badge?: string
  badgeColor?: string
  height?: number
}

function DataFrameGrid({ rows, label, badge, badgeColor = 'bg-bdo-red/15 text-bdo-red-light', height = 400 }: DataFrameGridProps) {
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
      <div className="ag-theme-alpine w-full" style={{ height }}>
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

// ── Tabbed DataFrame viewer ───────────────────────────────────────────────────

type DataFrameTab = 'gl' | 'sub' | 'residual_gl' | 'residual_sub'

const TAB_CONFIG: { id: DataFrameTab; label: string; badgeColor: string }[] = [
  { id: 'gl', label: 'General Ledger (input)', badgeColor: 'bg-indigo-100 text-indigo-700' },
  { id: 'sub', label: 'Subledger (input)', badgeColor: 'bg-violet-100 text-violet-700' },
  { id: 'residual_gl', label: 'GL Residual (unmatched)', badgeColor: 'bg-amber-500/15 text-amber-300' },
  { id: 'residual_sub', label: 'Sub Residual (unmatched)', badgeColor: 'bg-amber-500/15 text-amber-300' },
]

function DataFrameTabs({ det }: { det: DeterministicResponse }) {
  const [activeTab, setActiveTab] = useState<DataFrameTab>('gl')

  const dataMap: Record<DataFrameTab, Record<string, unknown>[]> = {
    gl: det.gl_records,
    sub: det.sub_records,
    residual_gl: det.residual_gl_records,
    residual_sub: det.residual_sub_records,
  }

  const activeCfg = TAB_CONFIG.find((t) => t.id === activeTab)!
  const rows = dataMap[activeTab]

  return (
    <div>
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-void-border mb-4 overflow-x-auto">
        {TAB_CONFIG.map((tab) => {
          const count = dataMap[tab.id].length
          const isActive = tab.id === activeTab
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
                isActive
                  ? 'border-bdo-red text-bdo-red-light font-medium'
                  : 'border-transparent text-white/40 hover:text-white/70 hover:border-void-border'
              }`}
            >
              {tab.label}
              <span
                className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                  isActive ? tab.badgeColor : 'bg-void-border text-white/50'
                }`}
              >
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Active grid */}
      <DataFrameGrid
        rows={rows}
        label={activeCfg.label}
        badge={`${rows.length} rows`}
        badgeColor={activeCfg.badgeColor}
        height={440}
      />
    </div>
  )
}

// ── Full analytics panel ──────────────────────────────────────────────────────

function DeterministicAnalytics({ det }: { det: DeterministicResponse }) {
  const s = det.summary
  const scenarioStats = useMemo(
    () => deriveScenarioStats(det.matches, s.scenario_amount_summaries),
    [det.matches, s.scenario_amount_summaries],
  )
  const reviewSheets = useMemo(() => buildDetReviewSheets(det), [det])
  const matchPct =
    s.total_gl_records > 0
      ? ((s.matched_gl_records / s.total_gl_records) * 100).toFixed(1)
      : '0'

  return (
    <div className="mb-8 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-white">Deterministic Matching — Results</h3>
        <p className="text-xs text-white/50 mt-0.5">
          {s.match_count} match{s.match_count !== 1 ? 'es' : ''} across{' '}
          {scenarioStats.length} active scenario{scenarioStats.length !== 1 ? 's' : ''}
        </p>
      </div>

      {/* KPI row — counts */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Matches', value: s.match_count.toLocaleString(), accent: 'blue' },
          {
            label: 'GL Matched',
            value: s.matched_gl_records.toLocaleString(),
            sub: `${matchPct}% of ${s.total_gl_records.toLocaleString()} GL rows`,
            accent: 'green',
          },
          {
            label: 'Sub Matched',
            value: s.matched_sub_records.toLocaleString(),
            accent: 'green',
          },
          {
            label: 'GL Residual',
            value: s.unmatched_gl_records.toLocaleString(),
            sub: 'to probabilistic pool',
            accent: s.unmatched_gl_records > 0 ? 'amber' : 'gray',
          },
        ].map(({ label, value, sub, accent }) => {
          const cls = {
            blue: 'bg-bdo-red/8 border-bdo-red/20 text-white',
            green: 'bg-emerald-500/8 border-emerald-500/20 text-white',
            amber: 'bg-amber-500/8 border-amber-500/20 text-white',
            gray: 'bg-void-elevated border-void-border text-white',
          }[accent]
          return (
            <div key={label} className={`border rounded-lg p-4 ${cls}`}>
              <p className="text-xs font-medium opacity-60 uppercase tracking-wide">{label}</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{value}</p>
              {sub && <p className="text-xs mt-0.5 opacity-60">{sub}</p>}
            </div>
          )
        })}
      </div>

      {/* KPI row — dollar totals */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="border border-emerald-500/20 bg-emerald-500/8 rounded-lg p-4">
          <p className="text-xs font-medium text-emerald-400 uppercase tracking-wide">
            Total Matched GL Amount
          </p>
          <p className="text-2xl font-bold text-emerald-300 tabular-nums mt-1">
            {fmtUsd(s.total_matched_gl_amount)}
          </p>
          <p className="text-xs text-emerald-400 mt-0.5">across all {s.match_count} matches</p>
        </div>
        <div className="border border-emerald-500/20 bg-emerald-500/8 rounded-lg p-4">
          <p className="text-xs font-medium text-emerald-400 uppercase tracking-wide">
            Total Matched Sub Amount
          </p>
          <p className="text-2xl font-bold text-emerald-300 tabular-nums mt-1">
            {fmtUsd(s.total_matched_sub_amount)}
          </p>
          <p className="text-xs text-emerald-400 mt-0.5">
            variance{' '}
            <span
              className={
                Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount) < 0.01
                  ? 'text-emerald-400 font-medium'
                  : 'text-amber-300 font-medium'
              }
            >
              {fmtUsd(Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount))}
            </span>
          </p>
        </div>
      </div>

      {/* BANS Analysis */}
      <BansSection det={det} />

      {/* Per-scenario cards */}
      <div>
        <h4 className="text-sm font-semibold text-white mb-3">Breakdown by Method</h4>
        <div className="space-y-3">
          {scenarioStats.map((stats) => (
            <ScenarioCard key={stats.id} stats={stats} totalMatches={s.match_count} />
          ))}
          {scenarioStats.length === 0 && (
            <p className="text-sm text-white/35 italic">No matches were produced.</p>
          )}
        </div>
      </div>

      {/* Matched records — AG Grid */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-white">
            Matched Records{' '}
            <span className="font-normal text-white/35 text-xs">({det.matches.length} rows)</span>
          </h4>
          <p className="text-xs text-white/35">Sort · filter · resize any column</p>
        </div>
        <MatchedRecordsGrid
          matches={det.matches}
          glRecords={det.gl_records}
          subRecords={det.sub_records}
        />
      </div>

      {/* Source & residual DataFrames */}
      <div>
        <h4 className="text-sm font-semibold text-white mb-1">Source & Residual Data</h4>
        <p className="text-xs text-white/50 mb-4">
          Inspect the full GL and Subledger inputs alongside the unmatched residual rows that will
          flow into the probabilistic matching pool.
        </p>
        <DataFrameTabs det={det} />
      </div>

      <DownloadPanel
        filename={`det_review_${det.session_id.slice(0, 8)}`}
        sheets={reviewSheets}
      />

      <div className="border-t border-dashed border-void-border pt-4">
        <p className="text-xs text-white/35">
          Review the results above, then confirm to advance the session. The{' '}
          {s.unmatched_gl_records.toLocaleString()} unmatched GL records will enter the
          probabilistic matching pool.
        </p>
      </div>
    </div>
  )
}

// ── Confirm result ────────────────────────────────────────────────────────────

function ReviewResult({ data }: { data: DeterministicReviewResponse }) {
  return (
    <div className="mt-5 space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Deterministic Matches', value: data.deterministic_match_count },
          { label: 'GL Residual', value: data.residual_gl_count },
          { label: 'Sub Residual', value: data.residual_sub_count },
        ].map(({ label, value }) => (
          <div key={label} className="bg-void-elevated border border-void-border rounded-xl p-4 text-center">
            <p className="text-xs text-white/50">{label}</p>
            <p className="text-2xl font-bold text-white mt-1">{value}</p>
          </div>
        ))}
      </div>
      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 text-sm text-emerald-300">
        Review confirmed. State: <strong>{data.state}</strong>. Snapshot:{' '}
        <span className="font-mono">{data.snapshot.key}</span>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DeterministicReviewStep({ sessionId, onSuccess }: Props) {
  const det = useMemo<DeterministicResponse | null>(() => {
    const raw = sessionStorage.getItem(`deterministic_result_${sessionId}`)
    return raw ? (JSON.parse(raw) as DeterministicResponse) : null
  }, [sessionId])

  const mutation = useMutation({
    mutationFn: () => confirmDeterministicReview(sessionId),
    onSuccess,
  })

  return (
    <div className="glass-card p-6">
      {det ? (
        <DeterministicAnalytics det={det} />
      ) : (
        <div className="bg-void-elevated border border-void-border rounded-xl p-3 text-sm text-white/50 mb-6">
          Deterministic analytics not available (run the Deterministic step in this browser session
          to see the breakdown here).
        </div>
      )}

      <h2 className="text-base font-semibold text-white mb-1">Confirm Deterministic Review</h2>
      <p className="text-sm text-white/50 mb-2">
        This is a <strong>confirm-only</strong> step — no recomputation occurs. Confirming locks the
        deterministic results and advances the session to probabilistic matching on the residual pool.
      </p>
      <div className="bg-bdo-red/8 border border-bdo-red/20 rounded-xl p-3 text-sm text-white/70 mb-5">
        A snapshot is captured before the state transition.
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
        {mutation.isPending ? 'Confirming…' : 'Confirm Deterministic Review'}
      </button>

      {mutation.data && <ReviewResult data={mutation.data} />}
    </div>
  )
}
