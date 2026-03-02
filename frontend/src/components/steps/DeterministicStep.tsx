import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef, ColGroupDef, ValueFormatterParams } from 'ag-grid-community'
import { runDeterministic } from '@/api/endpoints'
import type {
  DeterministicResponse,
  MatchRecord,
  ScenarioAmountSummary,
  PreprocessingResponse,
  NormalizationEntry,
} from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'
import DownloadPanel, { type PanelSheet } from '@/components/DownloadPanel'

interface Props {
  sessionId: string
  onSuccess: () => void
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtUsd(v: number): string {
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

// ── Download sheet builders ───────────────────────────────────────────────────

function buildVendorMapSheets(prep: PreprocessingResponse): PanelSheet[] {
  const mapRows = prep.vendor_normalization_map.map((e) => ({
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
    { Metric: 'Total GL Vendors', Value: prep.normalization_summary.total_unique_gl_vendors },
    { Metric: 'Tier 1 (Rules)',   Value: prep.normalization_summary.tier1_count },
    { Metric: 'Tier 2 (Fuzzy)',   Value: prep.normalization_summary.tier2_count },
    { Metric: 'Tier 3 (AI Stub)', Value: prep.normalization_summary.tier3_count },
    { Metric: 'Threshold',        Value: `${(prep.normalization_summary.threshold_used * 100).toFixed(0)}%` },
    { Metric: 'Alias Version',    Value: prep.normalization_summary.alias_version },
  ]
  return [
    { id: 'vendor_map',   label: 'Vendor Normalization Map', name: 'Vendor Map',   rows: mapRows },
    { id: 'norm_summary', label: 'Normalization Summary',    name: 'Norm Summary', rows: summaryRows },
  ]
}

function buildDetSheets(data: DeterministicResponse): PanelSheet[] {
  const s = data.summary
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
  const matchRows = data.matches.map((m) => ({
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
  const multiGroups = data.matches.filter((m) => m.grouping_type !== 'one_to_one')
  const glResiPct = s.total_gl_records > 0 ? (s.unmatched_gl_records / s.total_gl_records) * 100 : 0
  const subResiPct = s.total_sub_records > 0 ? (s.unmatched_sub_records / s.total_sub_records) * 100 : 0
  const bansRows: Record<string, unknown>[] = [
    { Section: 'B — Big Groups', Metric: 'N:1 / 1:N multi-record matches',      Value: multiGroups.length,           Flag: multiGroups.length === 0 ? 'OK' : multiGroups.length <= 5 ? 'WARN' : 'ALERT' },
    { Section: 'B — Big Groups', Metric: 'Largest group (total records)',         Value: multiGroups.length > 0 ? Math.max(...multiGroups.map((m) => m.record_ids_A.length + m.record_ids_B.length)) : 0, Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Matched GL Amount',                     Value: s.total_matched_gl_amount,    Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Matched Sub Amount',                    Value: s.total_matched_sub_amount,   Flag: 'INFO' },
    { Section: 'A — Amount',     Metric: 'Variance |GL − Sub|',                   Value: variance,                     Flag: variance < 0.01 ? 'OK' : variancePct < 0.1 ? 'WARN' : 'ALERT' },
    { Section: 'A — Amount',     Metric: 'Variance %',                            Value: `${variancePct.toFixed(3)}%`, Flag: variance < 0.01 ? 'OK' : variancePct < 0.1 ? 'WARN' : 'ALERT' },
    { Section: 'N — Residuals',  Metric: 'GL Total Rows',                         Value: s.total_gl_records,           Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'GL Residual Rows',                      Value: s.unmatched_gl_records,       Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'GL Residual %',                         Value: `${glResiPct.toFixed(1)}%`,   Flag: glResiPct < 10 ? 'OK' : glResiPct < 30 ? 'WARN' : 'ALERT' },
    { Section: 'N — Residuals',  Metric: 'Sub Total Rows',                        Value: s.total_sub_records,          Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'Sub Residual Rows',                     Value: s.unmatched_sub_records,      Flag: 'INFO' },
    { Section: 'N — Residuals',  Metric: 'Sub Residual %',                        Value: `${subResiPct.toFixed(1)}%`,  Flag: subResiPct < 10 ? 'OK' : subResiPct < 30 ? 'WARN' : 'ALERT' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 1 — Exact (100% conf.)',       Value: s.scenario_counts['1'] ?? 0, Flag: 'OK' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 2 — Vendor+Amt+Date (95%)',    Value: s.scenario_counts['2'] ?? 0, Flag: 'OK' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 3 — Amt+Entity+Date (85%)',    Value: s.scenario_counts['3'] ?? 0, Flag: (s.scenario_counts['3'] ?? 0) === 0 ? 'OK' : 'WARN' },
    { Section: 'S — Scenarios',  Metric: 'Scenario 4 — Group Sum N:1/1:N (75%)', Value: s.scenario_counts['4'] ?? 0, Flag: (s.scenario_counts['4'] ?? 0) === 0 ? 'OK' : (s.scenario_counts['4'] ?? 0) <= 3 ? 'WARN' : 'ALERT' },
  ]

  return [
    { id: 'summary',      label: 'Summary',                                           name: 'Summary',         rows: summaryRows },
    { id: 'bans',         label: 'BANS Report',                                       name: 'BANS Report',     rows: bansRows },
    { id: 'matches',      label: `Matched Records (${data.matches.length})`,          name: 'Matched Records', rows: matchRows },
    { id: 'gl_input',     label: `GL Input (${data.gl_records.length})`,              name: 'GL Input',        rows: data.gl_records as Record<string, unknown>[] },
    { id: 'sub_input',    label: `Sub Input (${data.sub_records.length})`,            name: 'Sub Input',       rows: data.sub_records as Record<string, unknown>[] },
    { id: 'gl_residual',  label: `GL Residual (${data.residual_gl_records.length})`,  name: 'GL Residual',     rows: data.residual_gl_records as Record<string, unknown>[] },
    { id: 'sub_residual', label: `Sub Residual (${data.residual_sub_records.length})`, name: 'Sub Residual',   rows: data.residual_sub_records as Record<string, unknown>[] },
  ]
}

// ── Preprocessing recap ───────────────────────────────────────────────────────

const TIER_META = {
  tier1: {
    label: 'Tier 1 — Alias Map & Rules',
    color: 'border-green-300 bg-green-50',
    badge: 'bg-green-100 text-green-800',
    dot: 'bg-green-500',
    desc: 'Direct lookup in the alias dictionary, then deterministic text normalization: lowercasing, punctuation removal, iterative legal-suffix stripping (LLC, Corp, Inc, Ltd, Co, …), and stopword removal. No ambiguity — if a vendor appears in the alias map or its cleaned form matches exactly, it resolves here.',
  },
  tier2: {
    label: 'Tier 2 — NLP Fuzzy Match',
    color: 'border-blue-300 bg-blue-50',
    badge: 'bg-blue-100 text-blue-800',
    dot: 'bg-blue-500',
    desc: 'Token-sort fuzzy similarity (rapidfuzz) against all Subledger vendor names. A match is accepted when similarity ≥ threshold (default 90%). Token-sort scoring reorders tokens alphabetically before comparing, which handles word-order variants ("Acme Corp" vs "Corp Acme") robustly without over-matching subsets.',
  },
  tier3: {
    label: 'Tier 3 — AI Stub',
    color: 'border-purple-300 bg-purple-50',
    badge: 'bg-purple-100 text-purple-800',
    dot: 'bg-purple-500',
    desc: 'Vendors that could not be resolved by Tier 1 or Tier 2 pass to the AI stub. Each vendor receives its own normalized form as its Vendor_Normalized key (no cross-file match). These records enter the residual pool for probabilistic and AI matching in later phases.',
  },
}

function TierExamples({
  tier,
  entries,
}: {
  tier: 'tier1' | 'tier2' | 'tier3'
  entries: NormalizationEntry[]
}) {
  const meta = TIER_META[tier]
  const examples = entries.filter((e) => e.match_source === tier).slice(0, 5)
  if (examples.length === 0) return null

  const showSub = tier !== 'tier3'

  return (
    <div className={`border rounded-lg overflow-hidden ${meta.color}`}>
      <div className="px-4 py-3 flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${meta.dot}`} />
        <span className="text-sm font-semibold text-gray-800">{meta.label}</span>
        <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${meta.badge}`}>
          {entries.filter((e) => e.match_source === tier).length} vendors
        </span>
      </div>

      <div className="px-4 pb-3">
        <p className="text-xs text-gray-600 mb-3 leading-relaxed">{meta.desc}</p>

        <div className="overflow-x-auto">
          <table className="w-full text-xs bg-white rounded border border-gray-200 overflow-hidden">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left py-1.5 px-3 font-medium text-gray-500">GL Original</th>
                <th className="text-left py-1.5 px-3 font-medium text-gray-500">→ Normalized</th>
                {showSub && (
                  <th className="text-left py-1.5 px-3 font-medium text-gray-500">
                    Matched Sub Vendor
                  </th>
                )}
                {tier === 'tier2' && (
                  <th className="text-right py-1.5 px-3 font-medium text-gray-500">Similarity</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {examples.map((e, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="py-1.5 px-3 font-mono text-gray-700">{e.original_vendor}</td>
                  <td className="py-1.5 px-3">
                    <span className="font-mono font-semibold text-gray-900">
                      {e.normalized_vendor}
                    </span>
                    {e.original_vendor.toLowerCase().replace(/[^a-z0-9]/g, '') !==
                      e.normalized_vendor.toLowerCase().replace(/[^a-z0-9]/g, '') && (
                      <span className="ml-1.5 text-[10px] text-gray-400 italic">changed</span>
                    )}
                  </td>
                  {showSub && (
                    <td className="py-1.5 px-3 font-mono text-gray-500">
                      {e.matched_to ?? <span className="text-gray-300">—</span>}
                    </td>
                  )}
                  {tier === 'tier2' && (
                    <td className="py-1.5 px-3 text-right tabular-nums font-medium text-blue-600">
                      {e.similarity_score != null
                        ? `${(e.similarity_score * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function PreprocessingRecap({ prep }: { prep: PreprocessingResponse }) {
  const s = prep.normalization_summary
  const entries = prep.vendor_normalization_map
  const vendorSheets = useMemo(() => buildVendorMapSheets(prep), [prep])
  const total = s.total_unique_gl_vendors
  const matchedPct =
    total > 0 ? (((s.tier1_count + s.tier2_count) / total) * 100).toFixed(1) : '0'

  return (
    <div className="mb-8 space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">
          Preprocessing Complete — Vendor Normalization
        </h3>
        <p className="text-xs text-gray-500 mt-0.5">
          Alias version {s.alias_version} · threshold {(s.threshold_used * 100).toFixed(0)}% ·
          snapshot <span className="font-mono">{prep.snapshot.key}</span>
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'GL Unique Vendors', value: total, accent: 'gray' },
          {
            label: 'Matched to Sub',
            value: `${s.tier1_count + s.tier2_count}`,
            sub: `${matchedPct}% of GL vendors`,
            accent: 'green',
          },
          {
            label: 'Tier 1 (Rules)',
            value: s.tier1_count,
            sub: `${total > 0 ? ((s.tier1_count / total) * 100).toFixed(1) : 0}%`,
            accent: 'green',
          },
          {
            label: 'Tier 2 (Fuzzy)',
            value: s.tier2_count,
            sub: `${total > 0 ? ((s.tier2_count / total) * 100).toFixed(1) : 0}%`,
            accent: 'blue',
          },
        ].map(({ label, value, sub, accent }) => {
          const cls = {
            gray: 'bg-gray-50 border-gray-200 text-gray-900',
            green: 'bg-green-50 border-green-200 text-green-900',
            blue: 'bg-blue-50 border-blue-200 text-blue-900',
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

      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-2">
          What happened
        </h4>
        <p className="text-sm text-slate-700 leading-relaxed">
          The normalization pipeline processed <strong>{total}</strong> unique GL vendor names
          through a cascading 3-tier system. Each vendor passes through tiers in sequence — the
          moment a tier resolves the vendor, it stops.
        </p>
        <ul className="mt-3 space-y-2 text-sm text-slate-700">
          <li className="flex gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-green-500 flex-shrink-0 mt-1" />
            <span>
              <strong>Tier 1 resolved {s.tier1_count} vendors</strong> via alias dictionary lookup
              and deterministic text rules (lowercase, punctuation removal, legal-suffix stripping,
              stopword removal). These matches are exact and require zero fuzzy logic.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-500 flex-shrink-0 mt-1" />
            <span>
              <strong>Tier 2 resolved {s.tier2_count} vendors</strong> via NLP token-sort fuzzy
              similarity at a {(s.threshold_used * 100).toFixed(0)}% threshold. This handles
              abbreviations, word-order differences, and minor spelling variants.
            </span>
          </li>
          {s.tier3_count > 0 && (
            <li className="flex gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500 flex-shrink-0 mt-1" />
              <span>
                <strong>{s.tier3_count} vendors</strong> could not be matched to any Subledger
                counterpart. They are assigned a self-normalized key via the AI stub and enter the
                residual pool for probabilistic and AI matching in later phases.
              </span>
            </li>
          )}
        </ul>
        <p className="mt-3 text-sm text-slate-600">
          The result is a <strong>Vendor_Normalized</strong> column added to both GL and Subledger
          DataFrames. When a GL vendor matched a Sub vendor through Tier 1 or Tier 2, both records
          carry the <em>same</em> Vendor_Normalized key — enabling downstream exact-join matching in
          the deterministic phase.
        </p>
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-900">Examples by Tier</h4>
        <TierExamples tier="tier1" entries={entries} />
        <TierExamples tier="tier2" entries={entries} />
        <TierExamples tier="tier3" entries={entries} />
      </div>

      <DownloadPanel
        filename={`vendor_normalization_${prep.snapshot.key}`}
        sheets={vendorSheets}
      />

      <div className="border-t border-dashed border-gray-200 pt-6">
        <p className="text-xs text-gray-400 mb-4">
          Review the normalization above, then run deterministic matching on the cleaned records.
        </p>
      </div>
    </div>
  )
}

// ── Scenario metadata ─────────────────────────────────────────────────────────

const SCENARIO_META: Record<
  number,
  { label: string; confidence: string; color: string; dotColor: string; description: string }
> = {
  1: {
    label: 'Scenario 1 — Exact Match',
    confidence: '100%',
    color: 'border-green-300 bg-green-50',
    dotColor: 'bg-green-500',
    description:
      'All four dimensions match exactly: normalized vendor name, transaction amount (rounded to 2 d.p.), date, and entity. This is the strongest possible deterministic match — no ambiguity remains.',
  },
  2: {
    label: 'Scenario 2 — Vendor + Amount + Date Tolerance',
    confidence: '95%',
    color: 'border-blue-300 bg-blue-50',
    dotColor: 'bg-blue-500',
    description:
      'Normalized vendor and amount match exactly, with a date tolerance of ±60 days. Handles timing differences caused by accruals, cut-off periods, and processing delays between GL posting and subledger recording.',
  },
  3: {
    label: 'Scenario 3 — Amount + Entity + Date Tolerance',
    confidence: '85%',
    color: 'border-amber-300 bg-amber-50',
    dotColor: 'bg-amber-500',
    description:
      'Amount and entity match exactly within a ±60-day date window, but vendor names differ. Covers cases where vendor names are recorded inconsistently but the transaction amount and business unit make the pairing unambiguous.',
  },
  4: {
    label: 'Scenario 4 — Group Sum Match (N:1 / 1:N)',
    confidence: '75%',
    color: 'border-purple-300 bg-purple-50',
    dotColor: 'bg-purple-500',
    description:
      'Many GL records sum to one Subledger record, or one GL record equals a group of Subledger records. Groups are bounded at 5 records and must share the same entity. Handles invoice consolidation, instalment splits, and multi-line journal entries.',
  },
}

// ── Per-scenario stats ────────────────────────────────────────────────────────

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
            <span className="text-sm font-semibold text-gray-900">{meta.label}</span>
            <span className="text-xs font-bold text-gray-600 flex-shrink-0">
              {meta.confidence} confidence
            </span>
          </div>
          <p className="text-xs text-gray-600 mt-1.5 leading-relaxed">{meta.description}</p>
        </div>
      </div>
      <div className="px-4 pb-4 flex items-center gap-6 border-t border-black/5 pt-3 flex-wrap">
        <div>
          <p className="text-2xl font-bold text-gray-900 tabular-nums">{stats.count}</p>
          <p className="text-xs text-gray-500">
            match{stats.count !== 1 ? 'es' : ''} ({pct}% of total)
          </p>
        </div>
        <div className="h-8 w-px bg-black/10" />
        <div>
          <p className="text-lg font-bold text-gray-700 tabular-nums">{stats.glRecords}</p>
          <p className="text-xs text-gray-500">GL records</p>
        </div>
        <div>
          <p className="text-lg font-bold text-gray-700 tabular-nums">{stats.subRecords}</p>
          <p className="text-xs text-gray-500">Sub records</p>
        </div>
        <div className="h-8 w-px bg-black/10" />
        <div>
          <p className="text-lg font-bold text-emerald-700 tabular-nums">
            {fmtUsd(stats.totalGlAmount)}
          </p>
          <p className="text-xs text-gray-500">GL amount</p>
        </div>
        <div>
          <p className="text-lg font-bold text-emerald-700 tabular-nums">
            {fmtUsd(stats.totalSubAmount)}
          </p>
          <p className="text-xs text-gray-500">Sub amount</p>
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
      <h4 className="text-sm font-semibold text-gray-900 mb-1">BANS Analysis</h4>
      <p className="text-xs text-gray-500 mb-4">
        Big groups · Amount anomalies · Notable residuals · Scenario sensitivity
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

        {/* B — Big Groups */}
        <div className="border border-gray-200 rounded-lg p-4">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-3">
            B — Big Groups
          </p>
          <p className="text-2xl font-bold text-gray-900 tabular-nums">{multiGroups.length}</p>
          <p className="text-xs text-gray-500 mb-3">N:1 / 1:N multi-record matches</p>
          {multiGroups.length > 0 ? (
            <>
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-1 pr-2 font-medium text-gray-500">Match ID</th>
                    <th className="text-center py-1 px-2 font-medium text-gray-500">GL</th>
                    <th className="text-center py-1 px-2 font-medium text-gray-500">Sub</th>
                    <th className="text-left py-1 pl-2 font-medium text-gray-500">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {multiGroups.slice(0, 6).map((m) => (
                    <tr key={m.match_id}>
                      <td className="py-1 pr-2 font-mono text-gray-700 truncate max-w-[120px]">
                        {m.match_id}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-gray-900">
                        {m.record_ids_A.length}
                      </td>
                      <td className="py-1 px-2 text-center font-bold text-gray-900">
                        {m.record_ids_B.length}
                      </td>
                      <td className="py-1 pl-2 text-gray-600">{m.grouping_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {multiGroups.length > 6 && (
                <p className="text-[10px] text-gray-400 mt-1.5">
                  +{multiGroups.length - 6} more — see Matched Records grid below
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-green-600">
              All matches are 1:1 — no complex groupings detected.
            </p>
          )}
        </div>

        {/* A — Amount Variance */}
        <div className="border border-gray-200 rounded-lg p-4">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-3">
            A — Amount Variance
          </p>
          <div className="space-y-2 text-xs">
            {[
              { label: 'Matched GL',  value: fmtUsd(s.total_matched_gl_amount) },
              { label: 'Matched Sub', value: fmtUsd(s.total_matched_sub_amount) },
            ].map(({ label, value }) => (
              <div key={label} className="flex justify-between">
                <span className="text-gray-500">{label}</span>
                <span className="font-medium tabular-nums">{value}</span>
              </div>
            ))}
            <div className="border-t border-gray-100 pt-2 flex justify-between">
              <span className="text-gray-500">Variance</span>
              <span
                className={`font-bold tabular-nums ${
                  variance < 0.01 ? 'text-green-600' : variancePct < 0.1 ? 'text-amber-600' : 'text-red-600'
                }`}
              >
                {fmtUsd(variance)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Variance %</span>
              <span
                className={`font-medium ${
                  variance < 0.01 ? 'text-green-600' : variancePct < 0.1 ? 'text-amber-600' : 'text-red-600'
                }`}
              >
                {variancePct.toFixed(3)}%
              </span>
            </div>
          </div>
          <div
            className={`mt-3 p-2 rounded text-[11px] ${
              variance < 0.01
                ? 'bg-green-50 text-green-700'
                : variancePct < 0.1
                  ? 'bg-amber-50 text-amber-700'
                  : 'bg-red-50 text-red-700'
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
        <div className="border border-gray-200 rounded-lg p-4">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-3">
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
                  <span className="text-gray-500">{label}</span>
                  <span
                    className={`font-semibold ${
                      pct < 10 ? 'text-green-700' : pct < 30 ? 'text-amber-600' : 'text-red-600'
                    }`}
                  >
                    {count.toLocaleString()} / {total.toLocaleString()} ({pct.toFixed(1)}%)
                  </span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full ${
                      pct < 10 ? 'bg-green-400' : pct < 30 ? 'bg-amber-400' : 'bg-red-400'
                    }`}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-gray-400 mt-3">
            Residual records advance to the probabilistic matching pool.
          </p>
        </div>

        {/* S — Scenario Sensitivity */}
        <div className="border border-gray-200 rounded-lg p-4">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-3">
            S — Scenario Sensitivity
          </p>
          <div className="space-y-2">
            {[
              { label: 'Sc. 1 — Exact (100%)',              key: '1', risk: false },
              { label: 'Sc. 2 — Vendor + Amt + Date (95%)', key: '2', risk: false },
              { label: 'Sc. 3 — Amt + Entity + Date (85%)', key: '3', risk: true },
              { label: 'Sc. 4 — Group Sum N:1/1:N (75%)',  key: '4', risk: true },
            ].map(({ label, key, risk }) => {
              const count = s.scenario_counts[key] ?? 0
              return (
                <div key={key} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-gray-600 flex-1 truncate">{label}</span>
                  <span
                    className={`font-bold tabular-nums flex-shrink-0 ${
                      risk && count > 0 ? (key === '4' ? 'text-red-600' : 'text-amber-600') : 'text-gray-900'
                    }`}
                  >
                    {count}
                  </span>
                </div>
              )
            })}
          </div>
          {(sc3 > 0 || sc4 > 0) ? (
            <div className="mt-3 p-2 bg-amber-50 rounded text-[11px] text-amber-700">
              {sc4 > 0 &&
                `${sc4} group-sum match${sc4 !== 1 ? 'es' : ''} (Sc. 4) use aggregation — verify groupings. `}
              {sc3 > 0 &&
                `${sc3} vendor-mismatch match${sc3 !== 1 ? 'es' : ''} (Sc. 3) skipped name check — review.`}
            </div>
          ) : (
            <div className="mt-3 p-2 bg-green-50 rounded text-[11px] text-green-700">
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
    { headerName: 'Match', children: matchChildren },
    { headerName: 'General Ledger', children: makeChildColDefs(glCols, 'gl__') },
    { headerName: 'Subledger',      children: makeChildColDefs(subCols, 'sub__') },
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

function DataFrameGrid({
  rows,
  label,
  badge,
  badgeColor = 'bg-blue-100 text-blue-700',
  height = 400,
}: DataFrameGridProps) {
  const colDefs = useMemo(() => buildDfColDefs(rows), [rows])
  if (rows.length === 0) {
    return (
      <div className="border border-gray-200 rounded-lg p-5 text-center bg-gray-50">
        <p className="text-sm text-gray-500">{label} — 0 rows</p>
      </div>
    )
  }
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        {badge && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${badgeColor}`}>
            {badge}
          </span>
        )}
        <span className="text-xs text-gray-400 ml-auto">Sort · filter · resize any column</span>
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
  { id: 'gl',          label: 'General Ledger (input)',   badgeColor: 'bg-indigo-100 text-indigo-700' },
  { id: 'sub',         label: 'Subledger (input)',        badgeColor: 'bg-violet-100 text-violet-700' },
  { id: 'residual_gl', label: 'GL Residual (unmatched)',  badgeColor: 'bg-amber-100 text-amber-700' },
  { id: 'residual_sub', label: 'Sub Residual (unmatched)', badgeColor: 'bg-amber-100 text-amber-700' },
]

function DataFrameTabs({ det }: { det: DeterministicResponse }) {
  const [activeTab, setActiveTab] = useState<DataFrameTab>('gl')

  const dataMap: Record<DataFrameTab, Record<string, unknown>[]> = {
    gl:          det.gl_records,
    sub:         det.sub_records,
    residual_gl: det.residual_gl_records,
    residual_sub: det.residual_sub_records,
  }

  const activeCfg = TAB_CONFIG.find((t) => t.id === activeTab)!
  const rows = dataMap[activeTab]

  return (
    <div>
      <div className="flex gap-1 border-b border-gray-200 mb-4 overflow-x-auto">
        {TAB_CONFIG.map((tab) => {
          const count = dataMap[tab.id].length
          const isActive = tab.id === activeTab
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
                isActive
                  ? 'border-blue-500 text-blue-700 font-medium'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
              <span
                className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                  isActive ? tab.badgeColor : 'bg-gray-100 text-gray-500'
                }`}
              >
                {count}
              </span>
            </button>
          )
        })}
      </div>

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

// ── Deterministic result — full analytics panel ───────────────────────────────

function DeterministicResult({ data }: { data: DeterministicResponse }) {
  const s = data.summary
  const detSheets = useMemo(() => buildDetSheets(data), [data])
  const scenarioStats = useMemo(
    () => deriveScenarioStats(data.matches, s.scenario_amount_summaries),
    [data.matches, s.scenario_amount_summaries],
  )
  const matchPct =
    s.total_gl_records > 0
      ? ((s.matched_gl_records / s.total_gl_records) * 100).toFixed(1)
      : '0'

  return (
    <div className="mt-6 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Deterministic Matching — Results</h3>
        <p className="text-xs text-gray-500 mt-0.5">
          {s.match_count} match{s.match_count !== 1 ? 'es' : ''} across{' '}
          {scenarioStats.length} active scenario{scenarioStats.length !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Count KPIs */}
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
            blue: 'bg-blue-50 border-blue-200 text-blue-900',
            green: 'bg-green-50 border-green-200 text-green-900',
            amber: 'bg-amber-50 border-amber-200 text-amber-900',
            gray: 'bg-gray-50 border-gray-200 text-gray-900',
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

      {/* Dollar KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="border border-emerald-200 bg-emerald-50 rounded-lg p-4">
          <p className="text-xs font-medium text-emerald-700 uppercase tracking-wide">
            Total Matched GL Amount
          </p>
          <p className="text-2xl font-bold text-emerald-900 tabular-nums mt-1">
            {fmtUsd(s.total_matched_gl_amount)}
          </p>
          <p className="text-xs text-emerald-600 mt-0.5">across all {s.match_count} matches</p>
        </div>
        <div className="border border-emerald-200 bg-emerald-50 rounded-lg p-4">
          <p className="text-xs font-medium text-emerald-700 uppercase tracking-wide">
            Total Matched Sub Amount
          </p>
          <p className="text-2xl font-bold text-emerald-900 tabular-nums mt-1">
            {fmtUsd(s.total_matched_sub_amount)}
          </p>
          <p className="text-xs text-emerald-600 mt-0.5">
            variance{' '}
            <span
              className={
                Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount) < 0.01
                  ? 'text-emerald-700 font-medium'
                  : 'text-amber-600 font-medium'
              }
            >
              {fmtUsd(Math.abs(s.total_matched_gl_amount - s.total_matched_sub_amount))}
            </span>
          </p>
        </div>
      </div>

      {/* BANS Analysis */}
      <BansSection det={data} />

      {/* Per-scenario cards */}
      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-3">Breakdown by Method</h4>
        <div className="space-y-3">
          {scenarioStats.map((stats) => (
            <ScenarioCard key={stats.id} stats={stats} totalMatches={s.match_count} />
          ))}
          {scenarioStats.length === 0 && (
            <p className="text-sm text-gray-400 italic">No matches were produced.</p>
          )}
        </div>
      </div>

      {/* Matched records — AG Grid */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-semibold text-gray-900">
            Matched Records{' '}
            <span className="font-normal text-gray-400 text-xs">({data.matches.length} rows)</span>
          </h4>
          <p className="text-xs text-gray-400">Sort · filter · resize any column</p>
        </div>
        <MatchedRecordsGrid
          matches={data.matches}
          glRecords={data.gl_records}
          subRecords={data.sub_records}
        />
      </div>

      {/* Source & residual DataFrames */}
      <div>
        <h4 className="text-sm font-semibold text-gray-900 mb-1">Source & Residual Data</h4>
        <p className="text-xs text-gray-500 mb-4">
          Inspect the full GL and Subledger inputs alongside the unmatched residual rows that will
          flow into the probabilistic matching pool.
        </p>
        <DataFrameTabs det={data} />
      </div>

      <DownloadPanel
        filename={`deterministic_${data.session_id.slice(0, 8)}`}
        sheets={detSheets}
      />

      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Deterministic matching complete. State: <strong>{data.state}</strong>. Proceed to
        Deterministic Review to confirm and inspect full data tables.
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function DeterministicStep({ sessionId, onSuccess }: Props) {
  const prep = useState<PreprocessingResponse | null>(() => {
    const raw = sessionStorage.getItem(`preprocess_result_${sessionId}`)
    return raw ? (JSON.parse(raw) as PreprocessingResponse) : null
  })[0]

  const mutation = useMutation({
    mutationFn: () => runDeterministic(sessionId),
    onSuccess: (data) => {
      const key = `deterministic_result_${sessionId}`
      try {
        sessionStorage.setItem(key, JSON.stringify(data))
      } catch {
        try {
          sessionStorage.setItem(key, JSON.stringify({
            ...data,
            gl_records: [],
            sub_records: [],
            residual_gl_records: [],
            residual_sub_records: [],
          }))
        } catch {
          // Even the slim version exceeds quota — skip caching entirely.
        }
      }
      onSuccess()
    },
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      {prep ? (
        <PreprocessingRecap prep={prep} />
      ) : (
        <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-sm text-gray-500 mb-6">
          Preprocessing summary not available (run the Preprocess step in this browser session to
          see it here).
        </div>
      )}

      <h2 className="text-base font-semibold text-gray-900 mb-1">Deterministic Matching</h2>
      <p className="text-sm text-gray-500 mb-5">
        Run rule-based matching across 4 scenarios using the normalized vendor keys above.
        Confidence scores are assigned per scenario (100% → 95% → 85% → 75%). All results are
        authoritative and auto-confirmed.
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
