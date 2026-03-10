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
import { ChevronDown, ChevronRight, Check, XCircle, ArrowRight, Loader2, RefreshCw } from 'lucide-react'
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
      gl_ref:  _field(glRec, 'gl_id', 'ref'),
      sl_ref:  _field(subRec, 'subledger_id', 'ref'),
      gl_records: glRecords,
      sl_records: slRecords,
    }
  })
}

interface FiltersState {
  confidenceMin: number
  amountMin: string
  amountMax: string
  matchMethod: string
  dateFrom: string
  dateTo: string
}

const defaultFilters: FiltersState = {
  confidenceMin: 0,
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
      setError('No session found. Start from Load Files.')
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
      if (filters.confidenceMin > 0 && row.confidence < filters.confidenceMin / 100) return false
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
            className="flex items-center justify-center p-1 rounded hover:bg-muted"
            aria-label={row.getIsExpanded() ? 'Collapse' : 'Expand'}
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </button>
        ),
        size: 40,
      },
      {
        id: 'gl',
        header: 'General Ledger',
        columns: [
          { accessorKey: 'gl_entity', header: 'Entity', cell: (c) => c.getValue() },
          { accessorKey: 'gl_vendor', header: 'Vendor', cell: (c) => c.getValue() },
          { accessorKey: 'gl_date', header: 'Date', cell: (c) => c.getValue() },
          {
            accessorKey: 'gl_amount',
            header: 'Amount',
            cell: (c) => Number(c.getValue()).toLocaleString(undefined, { minimumFractionDigits: 2 }),
          },
        ],
      },
      {
        id: 'sl',
        header: 'Subledger',
        columns: [
          { accessorKey: 'sl_entity', header: 'Entity', cell: (c) => c.getValue() },
          { accessorKey: 'sl_vendor', header: 'Vendor', cell: (c) => c.getValue() },
          { accessorKey: 'sl_date', header: 'Date', cell: (c) => c.getValue() },
          {
            accessorKey: 'sl_amount',
            header: 'Amount',
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
            cell: ({ row }) => {
              const m = row.original
              const glN = m.gl_records.length
              const slN = m.sl_records.length
              const groupHint = (glN > 1 || slN > 1)
                ? ` · ${glN} GL × ${slN} Sub`
                : ''
              return `${m.match_method}${groupHint}`
            },
          },
          {
            accessorKey: 'confidence',
            header: 'Confidence',
            cell: (c) => (Number(c.getValue()) * 100).toFixed(0) + '%',
          },
          { accessorKey: 'status', header: 'Status', cell: (c) => c.getValue() },
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

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-12">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Loading reconciliation results…
        </div>
      </PageLayout>
    )
  }

  if (error) {
    return (
      <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" className="mt-4" onClick={() => navigate('/load-files')}>
              Back to Load Files
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
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">GL Rows Matched</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null ? summary.glMatched.toLocaleString() : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">GL Rows Not Matched</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null ? summary.glUnmatched.toLocaleString() : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Match Rate</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null ? `${(summary.matchRate * 100).toFixed(1)}%` : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Matched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null
                ? `$${summary.matchedAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Unmatched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null
                ? `$${summary.unmatchedAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
      </section>

      {/* 2. Match Breakdown — horizontal stacked bar */}
      <Card>
        <CardHeader>
          <CardTitle>Match Breakdown</CardTitle>
          <CardDescription>
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
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle>Reconciliation Summary</CardTitle>
              <CardDescription>AI-generated overview of processing, results, and improvement suggestions.</CardDescription>
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
      <Card>
        <CardHeader>
          <CardTitle>Match Review</CardTitle>
          <CardDescription>
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
          <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-muted/30 p-4">
            <div className="flex flex-col gap-1">
              <label htmlFor="confidence-slider" className="text-xs font-medium text-muted-foreground">
                Confidence (min %)
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="confidence-slider"
                  type="range"
                  min={0}
                  max={100}
                  value={filters.confidenceMin}
                  onChange={(e) => setFilters(f => ({ ...f, confidenceMin: Number(e.target.value) }))}
                  className="h-2 w-24 rounded-full md:w-32"
                  style={{
                    appearance: 'none',
                    background: `linear-gradient(to right, #e5e7eb ${filters.confidenceMin}%, #166534 ${filters.confidenceMin}%)`,
                  }}
                />
                <span className="text-xs tabular-nums text-muted-foreground">{filters.confidenceMin}%</span>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="amount-min" className="text-xs font-medium text-muted-foreground">Amount min</label>
              <Input id="amount-min" type="number" placeholder="Min" value={filters.amountMin}
                onChange={(e) => setFilters(f => ({ ...f, amountMin: e.target.value }))} className="h-8 w-24" />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="amount-max" className="text-xs font-medium text-muted-foreground">Amount max</label>
              <Input id="amount-max" type="number" placeholder="Max" value={filters.amountMax}
                onChange={(e) => setFilters(f => ({ ...f, amountMax: e.target.value }))} className="h-8 w-24" />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="match-method" className="text-xs font-medium text-muted-foreground">Match Method</label>
              <select id="match-method" value={filters.matchMethod}
                onChange={(e) => setFilters(f => ({ ...f, matchMethod: e.target.value }))}
                className="h-8 w-36 rounded-md border border-input bg-background px-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="all">All</option>
                <option value="Deterministic">Deterministic</option>
                <option value="Probabilistic">Probabilistic</option>
                <option value="AI">AI</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="date-from" className="text-xs font-medium text-muted-foreground">Date from</label>
              <Input id="date-from" type="date" value={filters.dateFrom}
                onChange={(e) => setFilters(f => ({ ...f, dateFrom: e.target.value }))} className="h-8 w-36" />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="date-to" className="text-xs font-medium text-muted-foreground">Date to</label>
              <Input id="date-to" type="date" value={filters.dateTo}
                onChange={(e) => setFilters(f => ({ ...f, dateTo: e.target.value }))} className="h-8 w-36" />
            </div>
          </div>

          {/* Bulk Action Toolbar + Process Updates button (right-aligned) */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground mr-1">
                {filteredData.length.toLocaleString()} rows
              </span>
              <Button size="sm" variant="outline" onClick={handleExpandAll}>Expand All</Button>
              <Button size="sm" variant="outline" onClick={handleCollapseAll}>Collapse All</Button>
              <Button size="sm" variant="outline" onClick={handleAcceptAll}>
                <Check className="size-3.5 mr-1" aria-hidden />
                Accept All
              </Button>
              <Button size="sm" variant="outline"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={handleRejectAll}>
                <XCircle className="size-3.5 mr-1" aria-hidden />
                Reject All
              </Button>
            </div>
            <Button size="sm" onClick={() => navigate('/detailed-analysis')}>
              Process Updates &amp; View Detailed Analysis
              <ArrowRight className="size-4 ml-1" aria-hidden />
            </Button>
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id} colSpan={header.colSpan}
                        className="whitespace-nowrap bg-muted/50">
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
                      <TableRow data-state={row.getIsExpanded() ? 'expanded' : undefined}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                      {row.getIsExpanded() && (
                        <TableRow key={`${row.id}-expanded`} className="bg-muted/20">
                          <TableCell colSpan={row.getVisibleCells().length} className="p-4">
                            <div className="space-y-4">
                              <div className="grid gap-4 text-sm md:grid-cols-2">
                                <div>
                                  <p className="mb-2 font-medium text-foreground">
                                    General Ledger {row.original.gl_records.length > 1 ? `(${row.original.gl_records.length} records)` : '(full)'}
                                  </p>
                                  <div className="space-y-3">
                                    {row.original.gl_records.map((rec, idx) => (
                                      <dl key={idx} className="grid grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground rounded border border-border/50 p-2 bg-background/50">
                                        <dt>Entity</dt>
                                        <dd className="font-mono">{_field(rec, 'entity')}</dd>
                                        <dt>Vendor</dt>
                                        <dd className="font-mono">{_field(rec, 'vendor_name', 'Vendor_Normalized', 'vendor')}</dd>
                                        <dt>Date</dt>
                                        <dd className="font-mono">{_field(rec, 'transaction_date', 'date')}</dd>
                                        <dt>Amount</dt>
                                        <dd className="font-mono">
                                          {Number(rec.amount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                        </dd>
                                        {(_field(rec, 'gl_id', 'ref')) && (
                                          <>
                                            <dt>Ref</dt>
                                            <dd className="font-mono">{_field(rec, 'gl_id', 'ref')}</dd>
                                          </>
                                        )}
                                      </dl>
                                    ))}
                                  </div>
                                </div>
                                <div>
                                  <p className="mb-2 font-medium text-foreground">
                                    Subledger {row.original.sl_records.length > 1 ? `(${row.original.sl_records.length} records)` : '(full)'}
                                  </p>
                                  <div className="space-y-3">
                                    {row.original.sl_records.map((rec, idx) => (
                                      <dl key={idx} className="grid grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground rounded border border-border/50 p-2 bg-background/50">
                                        <dt>Entity</dt>
                                        <dd className="font-mono">{_field(rec, 'entity')}</dd>
                                        <dt>Vendor</dt>
                                        <dd className="font-mono">{_field(rec, 'vendor_name', 'Vendor_Normalized', 'vendor')}</dd>
                                        <dt>Date</dt>
                                        <dd className="font-mono">{_field(rec, 'transaction_date', 'date')}</dd>
                                        <dt>Amount</dt>
                                        <dd className="font-mono">
                                          {Number(rec.amount ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                        </dd>
                                        {(_field(rec, 'subledger_id', 'ref')) && (
                                          <>
                                            <dt>Ref</dt>
                                            <dd className="font-mono">{_field(rec, 'subledger_id', 'ref')}</dd>
                                          </>
                                        )}
                                      </dl>
                                    ))}
                                  </div>
                                </div>
                              </div>
                              <p className="text-xs text-muted-foreground">
                                Method: {row.original.match_method} · Confidence: {(row.original.confidence * 100).toFixed(0)}%
                              </p>
                              <div className="flex flex-wrap gap-2">
                                <Button size="sm" variant="default" onClick={() => handleAccept(row.original.id)}>
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
