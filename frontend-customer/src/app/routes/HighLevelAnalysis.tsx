import { Fragment, useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
  type ColumnDef,
  type ExpandedState,
} from '@tanstack/react-table'
import { ChevronDown, ChevronRight, Check, XCircle, ArrowRight, Loader2, RefreshCw, HelpCircle } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  RECON_SESSION_ID_KEY,
  getConsolidation,
  getSummaryNarrative,
  type FinalConsolidationResponse,
} from '@/api/endpoints'

// White card styling (matches Load & Clean Data page)
const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtAmount(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}

// Colours: Deterministic / Probabilistic / AI / Unmatched
const LAYER_COLORS = {
  deterministic: '#16a34a',
  probabilistic: '#2563eb',
  ai:            '#7c3aed',
  unmatched:     '#d97706',
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type MatchMethod = 'Deterministic' | 'Probabilistic' | 'AI'
export type MatchStatus = 'Pending' | 'Accepted' | 'Overridden' | 'Unmatched'

export interface MatchRow {
  id: string
  gl_entity: string
  gl_vendor: string
  gl_date: string
  gl_amount: number
  sl_entity: string
  sl_vendor: string
  sl_date: string
  sl_amount: number
  match_method: MatchMethod
  confidence: number
  status: MatchStatus
  reasoning_narrative?: string
  gl_ref?: string
  sl_ref?: string
  /** All GL records in this match (one-to-many or many-to-one) */
  gl_records: Record<string, unknown>[]
  /** All Subledger records in this match (one-to-many or many-to-one) */
  sl_records: Record<string, unknown>[]
}

function _field(rec: Record<string, unknown> | undefined, ...keys: string[]): string {
  if (!rec) return ''
  for (const k of keys) {
    const v = rec[k]
    if (v !== undefined && v !== null) return String(v)
  }
  return ''
}

function matchesToRows(
  finalMatches: Record<string, unknown>[],
  glById: Map<string, Record<string, unknown>>,
  subById: Map<string, Record<string, unknown>>,
): MatchRow[] {
  return finalMatches.map((m, i) => {
    const layer = String(m.layer ?? '')
    const glIds = (m.record_ids_A as string[]) ?? []
    const subIds = (m.record_ids_B as string[]) ?? []
    const glRecords = glIds
      .map((id) => glById.get(String(id)))
      .filter((r): r is Record<string, unknown> => r != null)
    const slRecords = subIds
      .map((id) => subById.get(String(id)))
      .filter((r): r is Record<string, unknown> => r != null)
    const glRec = glRecords[0]
    const subRec = slRecords[0]

    let confidence = 0
    if (layer === 'deterministic') confidence = Number(m.confidence_score ?? 0)
    else if (layer === 'probabilistic') confidence = Number(m.final_similarity ?? m.confidence_score ?? 0)
    else if (layer === 'ai') confidence = Number(m.ai_confidence_score ?? m.confidence_score ?? 0)

    const matchMethod: MatchMethod =
      layer === 'deterministic' ? 'Deterministic' :
      layer === 'probabilistic' ? 'Probabilistic' : 'AI'

    // Summary fields use first record; amounts can be totals for multi-record matches
    const glAmount = glRecords.reduce((s, r) => s + Number(r.amount ?? 0), 0)
    const slAmount = slRecords.reduce((s, r) => s + Number(r.amount ?? 0), 0)

    return {
      id: String(m.match_id ?? i),
      gl_entity:  _field(glRec, 'entity'),
      gl_vendor:  _field(glRec, 'vendor_name', 'Vendor_Normalized', 'vendor'),
      gl_date:    _field(glRec, 'transaction_date', 'date'),
      gl_amount:  glAmount,
      sl_entity:  _field(subRec, 'entity'),
      sl_vendor:  _field(subRec, 'vendor_name', 'Vendor_Normalized', 'vendor'),
      sl_date:    _field(subRec, 'transaction_date', 'date'),
      sl_amount:  slAmount,
      match_method: matchMethod,
      confidence,
      status: 'Accepted',
      reasoning_narrative: layer === 'ai' ? String(m.reasoning_narrative ?? '') || undefined : undefined,
      gl_ref:  _field(glRec, 'gl_id', 'ref'),
      sl_ref:  _field(subRec, 'subledger_id', 'ref'),
      gl_records: glRecords,
      sl_records: slRecords,
    }
  })
}

interface FiltersState {
  confidenceMin: string
  confidenceMax: string
  amountMin: string
  amountMax: string
  matchMethod: string
  dateFrom: string
  dateTo: string
}

const defaultFilters: FiltersState = {
  confidenceMin: '',
  confidenceMax: '',
  amountMin: '',
  amountMax: '',
  matchMethod: 'all',
  dateFrom: '',
  dateTo: '',
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HighLevelAnalysis() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<FiltersState>(defaultFilters)
  const [expanded, setExpanded] = useState<ExpandedState>({})
  const [matches, setMatches] = useState<MatchRow[]>([])
  const [consolidation, setConsolidation] = useState<FinalConsolidationResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (!sessionId) {
      setError('No session found. Start from Load & Clean Data.')
      setLoading(false)
      return
    }
    getConsolidation(sessionId)
      .then((res) => {
        setConsolidation(res)
        const glById = new Map(
          (res.gl_records as Record<string, unknown>[]).map(r => [String(r.gl_id ?? ''), r])
        )
        const subById = new Map(
          (res.sub_records as Record<string, unknown>[]).map(r => [String(r.subledger_id ?? ''), r])
        )
        setMatches(matchesToRows(res.final_matches as Record<string, unknown>[], glById, subById))
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load consolidation results'))
      .finally(() => setLoading(false))
  }, [])

  // ── GL-perspective summary ──────────────────────────────────────────────────

  const summary = useMemo(() => {
    if (!consolidation) return null
    const glMatched   = (consolidation.gl_records as Record<string, unknown>[]).length
    const glUnmatched = (consolidation.residual_gl_records as Record<string, unknown>[]).length
    const glTotal     = glMatched + glUnmatched
    const matchRate   = glTotal > 0 ? glMatched / glTotal : 0
    const matchedAmount = (consolidation.gl_records as Record<string, unknown>[]).reduce(
      (sum, r) => sum + Number(r.amount ?? 0), 0
    )
    const unmatchedAmount = (consolidation.residual_gl_records as Record<string, unknown>[]).reduce(
      (sum, r) => sum + Number(r.amount ?? 0), 0
    )
    return { glMatched, glUnmatched, glTotal, matchRate, matchedAmount, unmatchedAmount }
  }, [consolidation])

  // ── Bar chart data (GL-perspective row counts + amounts per layer) ───────────

  const chartData = useMemo(() => {
    if (!consolidation || !summary) return []

    // GL id → amount
    const glAmtMap = new Map<string, number>()
    ;(consolidation.gl_records as Record<string, unknown>[]).forEach(r => {
      const id = String(r['gl_id'] ?? '')
      if (id) glAmtMap.set(id, Number(r['amount'] ?? 0))
    })
    ;(consolidation.residual_gl_records as Record<string, unknown>[]).forEach(r => {
      const id = String(r['gl_id'] ?? '')
      if (id) glAmtMap.set(id, Number(r['amount'] ?? 0))
    })

    // Count GL rows and sum amounts per match layer
    const glCount: Record<string, number> = { deterministic: 0, probabilistic: 0, ai: 0 }
    const amtByLayer: Record<string, number> = { deterministic: 0, probabilistic: 0, ai: 0 }
    ;(consolidation.final_matches as Record<string, unknown>[]).forEach(m => {
      const layer = String(m['layer'] ?? '')
      const glIds = (m['record_ids_A'] as string[]) ?? []
      if (layer in glCount) {
        glCount[layer] += glIds.length
        amtByLayer[layer] += glIds.reduce((s, id) => s + (glAmtMap.get(id) ?? 0), 0)
      }
    })

    const unmatchedAmount = (consolidation.residual_gl_records as Record<string, unknown>[]).reduce(
      (s, r) => s + Number(r['amount'] ?? 0), 0
    )

    return [
      { name: 'Deterministic', count: glCount.deterministic, amount: amtByLayer.deterministic, color: LAYER_COLORS.deterministic },
      { name: 'Probabilistic', count: glCount.probabilistic, amount: amtByLayer.probabilistic, color: LAYER_COLORS.probabilistic },
      { name: 'AI Matches',    count: glCount.ai,            amount: amtByLayer.ai,            color: LAYER_COLORS.ai },
      { name: 'Unmatched',     count: summary.glUnmatched,   amount: unmatchedAmount,           color: LAYER_COLORS.unmatched },
    ]
  }, [consolidation, summary])

  // ── Narrative ──────────────────────────────────────────────────────────────

  const [narrative, setNarrative]               = useState<string>('')
  const [narrativeLoading, setNarrativeLoading] = useState(false)

  const fetchNarrative = useCallback(() => {
    const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (!sessionId) return
    setNarrativeLoading(true)
    getSummaryNarrative(sessionId)
      .then(r => setNarrative(r.narrative))
      .catch(() => setNarrative(''))
      .finally(() => setNarrativeLoading(false))
  }, [])

  useEffect(() => {
    if (consolidation) fetchNarrative()
  }, [consolidation, fetchNarrative])

  // ── Filtering & table ──────────────────────────────────────────────────────

  const filteredData = useMemo(() => {
    return matches.filter((row) => {
      const confPct = row.confidence * 100
      if (filters.confidenceMin !== '' && confPct < Number(filters.confidenceMin)) return false
      if (filters.confidenceMax !== '' && confPct > Number(filters.confidenceMax)) return false
      if (filters.amountMin !== '' && row.gl_amount < Number(filters.amountMin)) return false
      if (filters.amountMax !== '' && row.gl_amount > Number(filters.amountMax)) return false
      if (filters.matchMethod !== 'all' && row.match_method !== filters.matchMethod) return false
      if (filters.dateFrom && row.gl_date < filters.dateFrom) return false
      if (filters.dateTo && row.gl_date > filters.dateTo) return false
      return true
    })
  }, [matches, filters])

  const columns = useMemo<ColumnDef<MatchRow, unknown>[]>(
    () => [
      {
        id: 'expander',
        header: '',
        cell: ({ row }) => (
          <button
            type="button"
            onClick={row.getToggleExpandedHandler()}
            className="flex items-center justify-center p-1 rounded hover:bg-muted hover:text-white"
            aria-label={row.getIsExpanded() ? 'Collapse' : 'Expand'}
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        ),
        size: 32,
      },
      {
        id: 'gl',
        header: 'General Ledger',
        columns: [
          { accessorKey: 'gl_entity', header: 'Entity', size: 65, cell: (c) => c.getValue() },
          { accessorKey: 'gl_vendor', header: 'Vendor', size: 130, cell: (c) => <span className="block truncate max-w-[120px]" title={String(c.getValue())}>{String(c.getValue())}</span> },
          { accessorKey: 'gl_date', header: 'Date', size: 95, cell: (c) => c.getValue() },
          {
            accessorKey: 'gl_amount',
            header: 'Amount',
            size: 90,
            cell: (c) => Number(c.getValue()).toLocaleString(undefined, { minimumFractionDigits: 2 }),
          },
        ],
      },
      {
        id: 'sl',
        header: 'Subledger',
        columns: [
          { accessorKey: 'sl_entity', header: 'Entity', size: 65, cell: (c) => c.getValue() },
          { accessorKey: 'sl_vendor', header: 'Vendor', size: 130, cell: (c) => <span className="block truncate max-w-[120px]" title={String(c.getValue())}>{String(c.getValue())}</span> },
          { accessorKey: 'sl_date', header: 'Date', size: 95, cell: (c) => c.getValue() },
          {
            accessorKey: 'sl_amount',
            header: 'Amount',
            size: 90,
            cell: (c) => Number(c.getValue()).toLocaleString(undefined, { minimumFractionDigits: 2 }),
          },
        ],
      },
      {
        id: 'match_info',
        header: 'Match Info',
        columns: [
          {
            accessorKey: 'match_method',
            header: 'Method',
            size: 110,
            cell: ({ row }) => {
              const m = row.original
              const glN = m.gl_records.length
              const slN = m.sl_records.length
              const groupHint = (glN > 1 || slN > 1) ? ` · ${glN}×${slN}` : ''
              return `${m.match_method}${groupHint}`
            },
          },
          {
            accessorKey: 'confidence',
            header: 'Conf %',
            size: 70,
            cell: ({ row }) => {
              const pct = (row.original.confidence * 100).toFixed(0) + '%'
              const narrative = row.original.reasoning_narrative
              if (!narrative) return pct
              return (
                <span className="inline-flex items-center gap-1">
                  {pct}
                  <span className="relative group cursor-default">
                    <HelpCircle className="size-3.5 text-[#7c3aed]" aria-label="AI reasoning" />
                    <span className="pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-1.5 w-64 rounded-md bg-[#1a1a1a] px-3 py-2 text-xs text-white shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 whitespace-normal">
                      {narrative}
                    </span>
                  </span>
                </span>
              )
            },
          },
          {
            accessorKey: 'status',
            header: 'Status',
            size: 90,
            cell: ({ row }) => {
              const s = row.original.status
              return (
                <span className={
                  s === 'Unmatched'
                    ? 'text-destructive font-medium'
                    : s === 'Accepted'
                      ? 'text-green-700 font-medium'
                      : undefined
                }>
                  {s}
                </span>
              )
            },
          },
        ],
      },
    ],
    []
  )

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { expanded },
    onExpandedChange: setExpanded,
    getRowCanExpand: () => true,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  })

  const handleAccept       = (id: string) =>
    setMatches(prev => prev.map(r => r.id === id ? { ...r, status: 'Accepted' as MatchStatus } : r))
  const handleMarkUnmatched = (id: string) =>
    setMatches(prev => prev.map(r => r.id === id ? { ...r, status: 'Unmatched' as MatchStatus } : r))

  const handleExpandAll   = () => setExpanded(true)
  const handleCollapseAll = () => setExpanded({})
  const handleAcceptAll   = () => setMatches(prev => prev.map(r => ({ ...r, status: 'Accepted' as MatchStatus })))
  const handleRejectAll   = () => setMatches(prev => prev.map(r => ({ ...r, status: 'Unmatched' as MatchStatus })))

  const handleProcessAndNavigate = () => {
    const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (sessionId) {
      const manuallyUnmatched = matches.filter(r => r.status === 'Unmatched')
      localStorage.setItem(
        `recon-${sessionId}-manual-unmatched`,
        JSON.stringify(manuallyUnmatched.map(r => ({
          id: r.id,
          gl_records: r.gl_records,
          sl_records: r.sl_records,
        })))
      )
    }
    navigate('/detailed-analysis')
  }

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">
        <div className="flex items-center gap-2 text-sm text-[#1a1a1a] py-12">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Loading reconciliation results…
        </div>
      </PageLayout>
    )
  }

  if (error) {
    return (
      <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" className="mt-4" onClick={() => navigate('/load-files')}>
              Back to Load & Clean Data
            </Button>
          </CardContent>
        </Card>
      </PageLayout>
    )
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const glTotal = summary?.glTotal ?? 0

  return (
    <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">

      {/* 1. BANS — 5 GL-perspective KPI cards */}
      <section className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">GL Rows Matched</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-[#1a1a1a]">
              {summary != null ? summary.glMatched.toLocaleString() : '—'}
            </p>
          </CardContent>
        </Card>
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">GL Rows Not Matched</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-[#1a1a1a]">
              {summary != null ? summary.glUnmatched.toLocaleString() : '—'}
            </p>
          </CardContent>
        </Card>
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Match Rate</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-[#1a1a1a]">
              {summary != null ? `${(summary.matchRate * 100).toFixed(1)}%` : '—'}
            </p>
          </CardContent>
        </Card>
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Matched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-[#1a1a1a]">
              {summary != null
                ? `$${summary.matchedAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Unmatched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-[#1a1a1a]">
              {summary != null
                ? `$${summary.unmatchedAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
      </section>

      {/* 2. Match Breakdown — horizontal stacked bar */}
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Match Breakdown</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            GL row distribution across match phases (total: {glTotal.toLocaleString()} GL rows).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Stacked bar */}
          <div className="flex h-10 overflow-hidden rounded-lg">
            {chartData.map((seg) => {
              const pct = glTotal > 0 ? (seg.count / glTotal) * 100 : 0
              if (pct < 0.2) return null
              return (
                <div
                  key={seg.name}
                  style={{ width: `${pct}%`, backgroundColor: seg.color }}
                  className="flex items-center justify-center"
                  title={`${seg.name}: ${seg.count} rows`}
                >
                  {pct > 7 && (
                    <span className="text-xs font-semibold text-white">
                      {Math.round(pct)}%
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* Legend */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {chartData.map((seg) => (
              <div key={seg.name} className="flex items-start gap-2">
                <div
                  className="mt-0.5 h-3 w-3 shrink-0 rounded-sm"
                  style={{ backgroundColor: seg.color }}
                />
                <div>
                  <p className="text-sm font-medium text-foreground">{seg.name}</p>
                  <p className="text-xs text-muted-foreground">{seg.count.toLocaleString()} rows</p>
                  <p className="text-xs text-muted-foreground">{fmtAmount(seg.amount)}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 3. Narrative */}
      <Card className={whiteCardClass}>
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="text-[#1a1a1a]">Reconciliation Summary</CardTitle>
              <CardDescription className="text-[#1a1a1a]">AI-generated overview of processing, results, and improvement suggestions.</CardDescription>
            </div>
            {!narrativeLoading && (
              <Button variant="ghost" size="sm" onClick={fetchNarrative} title="Regenerate summary">
                <RefreshCw className="size-3.5" aria-hidden />
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {narrativeLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Generating AI summary…
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-foreground whitespace-pre-line">{narrative}</p>
          )}
        </CardContent>
      </Card>

      {/* 4. Match Review Table */}
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Match Review</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            Review and override matches. Expand a row for full details and actions.
            {consolidation && (
              <span className="ml-2 text-muted-foreground">
                ({matches.length.toLocaleString()} total matches)
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Filters Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-4 w-full rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="confidence-min" className="text-xs font-medium text-muted-foreground">Confidence min</label>
              <Input id="confidence-min" type="number" placeholder="Min %" value={filters.confidenceMin}
                onChange={(e) => setFilters(f => ({ ...f, confidenceMin: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="confidence-max" className="text-xs font-medium text-muted-foreground">Confidence max</label>
              <Input id="confidence-max" type="number" placeholder="Max %" value={filters.confidenceMax}
                onChange={(e) => setFilters(f => ({ ...f, confidenceMax: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="amount-min" className="text-xs font-medium text-muted-foreground">Amount min</label>
              <Input id="amount-min" type="number" placeholder="Min" value={filters.amountMin}
                onChange={(e) => setFilters(f => ({ ...f, amountMin: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="amount-max" className="text-xs font-medium text-muted-foreground">Amount max</label>
              <Input id="amount-max" type="number" placeholder="Max" value={filters.amountMax}
                onChange={(e) => setFilters(f => ({ ...f, amountMax: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="match-method" className="text-xs font-medium text-muted-foreground">Match Method</label>
              <select id="match-method" value={filters.matchMethod}
                onChange={(e) => setFilters(f => ({ ...f, matchMethod: e.target.value }))}
                className="h-8 w-full min-w-0 rounded-md border border-gray-200 bg-white px-2 text-sm text-[#1a1a1a] shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="all">All</option>
                <option value="Deterministic">Deterministic</option>
                <option value="Probabilistic">Probabilistic</option>
                <option value="AI">AI</option>
              </select>
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="date-from" className="text-xs font-medium text-muted-foreground">Date from</label>
              <Input id="date-from" type="date" value={filters.dateFrom}
                onChange={(e) => setFilters(f => ({ ...f, dateFrom: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
            <div className="flex flex-col gap-1 min-w-0">
              <label htmlFor="date-to" className="text-xs font-medium text-muted-foreground">Date to</label>
              <Input id="date-to" type="date" value={filters.dateTo}
                onChange={(e) => setFilters(f => ({ ...f, dateTo: e.target.value }))} className="h-8 w-full bg-white border-gray-200" />
            </div>
          </div>

          {/* Bulk Action Toolbar + Process Updates button (right-aligned) */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground mr-1">
                {filteredData.length.toLocaleString()} rows
              </span>
              <Button size="sm" variant="outline" onClick={handleExpandAll} className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">Expand All</Button>
              <Button size="sm" variant="outline" onClick={handleCollapseAll} className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">Collapse All</Button>
              <Button size="sm" variant="outline" onClick={handleAcceptAll} className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">
                <Check className="size-3.5 mr-1" aria-hidden />
                Accept All
              </Button>
              <Button size="sm" variant="outline"
                className="bg-white border-gray-200 text-destructive hover:bg-red-50 hover:text-destructive"
                onClick={handleRejectAll}>
                <XCircle className="size-3.5 mr-1" aria-hidden />
                Reject All
              </Button>
            </div>
            <Button size="sm" variant="brand" onClick={handleProcessAndNavigate}>
              Process Updates &amp; View Detailed Analysis
              <ArrowRight className="size-4 ml-1" aria-hidden />
            </Button>
          </div>

          {/* Table */}
          <div className="rounded-md border overflow-hidden">
            <Table className="w-full table-fixed">
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id} colSpan={header.colSpan}
                        style={header.column.getSize() ? { width: header.column.getSize() } : undefined}
                        className="whitespace-nowrap bg-[#333333] font-bold text-white">
                        {header.isPlaceholder
                          ? null
                          : flexRender(header.column.columnDef.header, header.getContext())}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={99} className="py-8 text-center text-sm text-muted-foreground">
                      No matches found.
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <Fragment key={row.id}>
                      <TableRow
                        data-state={row.getIsExpanded() ? 'expanded' : undefined}
                        className="hover:[&>td]:text-white"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className="py-2 text-sm">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                      {row.getIsExpanded() && (
                        <TableRow key={`${row.id}-expanded`} className="hover:bg-transparent">
                          <TableCell colSpan={row.getVisibleCells().length} className="p-4 bg-gray-50">
                            <div className="space-y-4">
                              <div className="grid gap-4 text-sm md:grid-cols-2">
                                <div>
                                  <p className="mb-2 font-semibold text-[#1a1a1a]">
                                    General Ledger {row.original.gl_records.length > 1 ? `(${row.original.gl_records.length} records)` : '(full)'}
                                  </p>
                                  <div className="space-y-3">
                                    {row.original.gl_records.map((rec, idx) => (
                                      <dl key={idx} className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border border-gray-300 p-3 bg-[#1a1a1a] text-white">
                                        <dt className="text-white/70">Entity</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'entity')}</dd>
                                        <dt className="text-white/70">Vendor</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'vendor_name', 'Vendor_Normalized', 'vendor')}</dd>
                                        <dt className="text-white/70">Date</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'transaction_date', 'date')}</dd>
                                        <dt className="text-white/70">Amount</dt>
                                        <dd className="font-mono text-white">
                                          {Number(rec.amount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                        </dd>
                                        {(_field(rec, 'gl_id', 'ref')) && (
                                          <>
                                            <dt className="text-white/70">Ref</dt>
                                            <dd className="font-mono text-white">{_field(rec, 'gl_id', 'ref')}</dd>
                                          </>
                                        )}
                                      </dl>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <p className="mb-2 font-semibold text-[#1a1a1a]">
                                    Subledger {row.original.sl_records.length > 1 ? `(${row.original.sl_records.length} records)` : '(full)'}
                                  </p>
                                  <div className="space-y-3">
                                    {row.original.sl_records.map((rec, idx) => (
                                      <dl key={idx} className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border border-gray-300 p-3 bg-[#1a1a1a] text-white">
                                        <dt className="text-white/70">Entity</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'entity')}</dd>
                                        <dt className="text-white/70">Vendor</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'vendor_name', 'Vendor_Normalized', 'vendor')}</dd>
                                        <dt className="text-white/70">Date</dt>
                                        <dd className="font-mono text-white">{_field(rec, 'transaction_date', 'date')}</dd>
                                        <dt className="text-white/70">Amount</dt>
                                        <dd className="font-mono text-white">
                                          {Number(rec.amount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                        </dd>
                                        {(_field(rec, 'subledger_id', 'ref')) && (
                                          <>
                                            <dt className="text-white/70">Ref</dt>
                                            <dd className="font-mono text-white">{_field(rec, 'subledger_id', 'ref')}</dd>
                                          </>
                                        )}
                                      </dl>
                                    ))}
                                  </div>
                                </div>
                              </div>
                              <p className="text-xs text-[#1a1a1a]/60">
                                Method: {row.original.match_method} · Confidence: {(row.original.confidence * 100).toFixed(0)}%
                              </p>
                              <div className="flex flex-wrap gap-2">
                                <Button size="sm" variant="brand" onClick={() => handleAccept(row.original.id)}>
                                  <Check className="size-3.5" aria-hidden />
                                  Accept Match
                                </Button>
                                <Button size="sm" variant="outline"
                                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                                  onClick={() => handleMarkUnmatched(row.original.id)}>
                                  <XCircle className="size-3.5" aria-hidden />
                                  Mark as Unmatched
                                </Button>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

    </PageLayout>
  )
}
