import { Fragment, useState, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
  type ColumnDef,
  type ExpandedState,
} from '@tanstack/react-table'
import { ChevronDown, ChevronRight, Check, Edit3, XCircle, ArrowRight, Loader2 } from 'lucide-react'
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
import { MatchingFunnel } from '@/components/analysis/MatchingFunnel'
import {
  RECON_SESSION_ID_KEY,
  getConsolidation,
  type FinalConsolidationResponse,
} from '@/api/endpoints'

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
    const glRec = glIds.length > 0 ? glById.get(String(glIds[0])) : undefined
    const subRec = subIds.length > 0 ? subById.get(String(subIds[0])) : undefined

    let confidence = 0
    if (layer === 'deterministic') confidence = Number(m.confidence_score ?? 0)
    else if (layer === 'probabilistic') confidence = Number(m.final_similarity ?? m.confidence_score ?? 0)
    else if (layer === 'ai') confidence = Number(m.ai_confidence_score ?? m.confidence_score ?? 0)

    const matchMethod: MatchMethod =
      layer === 'deterministic' ? 'Deterministic' :
      layer === 'probabilistic' ? 'Probabilistic' : 'AI'

    return {
      id: String(m.match_id ?? i),
      gl_entity:  String(glRec?.entity ?? ''),
      gl_vendor:  String(glRec?.vendor_name ?? glRec?.Vendor_Normalized ?? glRec?.vendor ?? ''),
      gl_date:    String(glRec?.transaction_date ?? glRec?.date ?? ''),
      gl_amount:  Number(glRec?.amount ?? 0),
      sl_entity:  String(subRec?.entity ?? ''),
      sl_vendor:  String(subRec?.vendor_name ?? subRec?.Vendor_Normalized ?? subRec?.vendor ?? ''),
      sl_date:    String(subRec?.transaction_date ?? subRec?.date ?? ''),
      sl_amount:  Number(subRec?.amount ?? 0),
      match_method: matchMethod,
      confidence,
      status: 'Accepted',
      gl_ref:  String(glRec?.gl_id ?? glRec?.ref ?? ''),
      sl_ref:  String(subRec?.subledger_id ?? subRec?.ref ?? ''),
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

  const summary = useMemo(() => {
    if (!consolidation) return null
    const s = consolidation.summary
    const total = s.total_match_count + s.residual_gl_count
    const matchRate = total > 0 ? s.total_match_count / total : 0
    const matchedAmount = (consolidation.gl_records as Record<string, unknown>[]).reduce(
      (sum, r) => sum + Number(r.amount ?? 0), 0
    )
    const unmatchedAmount = (consolidation.residual_gl_records as Record<string, unknown>[]).reduce(
      (sum, r) => sum + Number(r.amount ?? 0), 0
    )
    return { match_rate: matchRate, matched_amount: matchedAmount, unmatched_amount: unmatchedAmount }
  }, [consolidation])

  const funnelData = useMemo(() => {
    if (!consolidation) return []
    const s = consolidation.summary
    const total = s.total_match_count + s.residual_gl_count
    return [
      { name: 'Total Transactions', value: total, amount: 0 },
      { name: 'Deterministic Matches', value: s.deterministic_match_count, amount: 0 },
      { name: 'Probabilistic Matches', value: s.probabilistic_match_count, amount: 0 },
      { name: 'AI Matches', value: s.ai_match_count, amount: 0 },
      { name: 'Unmatched', value: s.residual_gl_count, amount: 0 },
    ]
  }, [consolidation])

  const narrative = useMemo(() => {
    if (!consolidation) return ''
    const s = consolidation.summary
    const total = s.total_match_count + s.residual_gl_count
    const rate = total > 0 ? ((s.total_match_count / total) * 100).toFixed(1) : '0'
    return (
      `This reconciliation processed ${total.toLocaleString()} GL transactions. ` +
      `${s.total_match_count.toLocaleString()} records were matched (${rate}% match rate). ` +
      `Deterministic matching resolved ${s.deterministic_match_count.toLocaleString()} records, ` +
      `probabilistic matching resolved ${s.probabilistic_match_count.toLocaleString()} additional records, ` +
      `and AI matching resolved ${s.ai_match_count.toLocaleString()} records. ` +
      `${s.residual_gl_count.toLocaleString()} GL records and ${s.residual_sub_count.toLocaleString()} ` +
      `subledger records remain unmatched.` +
      (s.rejected_count > 0 ? ` ${s.rejected_count.toLocaleString()} matches were rejected during review.` : '')
    )
  }, [consolidation])

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
          { accessorKey: 'match_method', header: 'Method', cell: (c) => c.getValue() },
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

  const handleAccept = (id: string) =>
    setMatches(prev => prev.map(r => r.id === id ? { ...r, status: 'Accepted' as MatchStatus } : r))
  const handleOverride = (id: string) =>
    setMatches(prev => prev.map(r => r.id === id ? { ...r, status: 'Overridden' as MatchStatus } : r))
  const handleMarkUnmatched = (id: string) =>
    setMatches(prev => prev.map(r => r.id === id ? { ...r, status: 'Unmatched' as MatchStatus } : r))

  const handleExpandAll  = () => setExpanded(true)
  const handleCollapseAll = () => setExpanded({})
  const handleAcceptAll  = () => setMatches(prev => prev.map(r => ({ ...r, status: 'Accepted' as MatchStatus })))
  const handleRejectAll  = () => setMatches(prev => prev.map(r => ({ ...r, status: 'Unmatched' as MatchStatus })))

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

  return (
    <PageLayout title="High-Level Analysis" description="Summary of reconciliation results and match review.">
      {/* 1. BANS */}
      <section className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Match Rate</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null
                ? `${(summary.match_rate <= 1 ? summary.match_rate * 100 : summary.match_rate).toFixed(1)}%`
                : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Matched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null
                ? `$${summary.matched_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Unmatched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {summary != null
                ? `$${summary.unmatched_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
                : '—'}
            </p>
          </CardContent>
        </Card>
      </section>

      {/* 2. Funnel */}
      <Card>
        <CardHeader>
          <CardTitle>Matching Funnel</CardTitle>
          <CardDescription>Flow from total transactions through match phases to unmatched.</CardDescription>
        </CardHeader>
        <CardContent>
          <MatchingFunnel data={funnelData} />
        </CardContent>
      </Card>

      {/* 3. Narrative */}
      <Card>
        <CardHeader>
          <CardTitle>Reconciliation Summary</CardTitle>
          <CardDescription>Overview of reconciliation outcome.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed text-foreground whitespace-pre-line">{narrative}</p>
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
                ({consolidation.summary.total_match_count.toLocaleString()} total matches)
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
                  className="h-2 w-24 rounded-full bg-muted accent-primary md:w-32"
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

          {/* Bulk Action Toolbar */}
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
                                  <p className="mb-2 font-medium text-foreground">General Ledger (full)</p>
                                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground">
                                    <dt>Entity</dt>
                                    <dd className="font-mono">{row.original.gl_entity}</dd>
                                    <dt>Vendor</dt>
                                    <dd className="font-mono">{row.original.gl_vendor}</dd>
                                    <dt>Date</dt>
                                    <dd className="font-mono">{row.original.gl_date}</dd>
                                    <dt>Amount</dt>
                                    <dd className="font-mono">
                                      {row.original.gl_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                    </dd>
                                    {row.original.gl_ref && (
                                      <>
                                        <dt>Ref</dt>
                                        <dd className="font-mono">{row.original.gl_ref}</dd>
                                      </>
                                    )}
                                  </dl>
                                </div>
                                <div>
                                  <p className="mb-2 font-medium text-foreground">Subledger (full)</p>
                                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground">
                                    <dt>Entity</dt>
                                    <dd className="font-mono">{row.original.sl_entity}</dd>
                                    <dt>Vendor</dt>
                                    <dd className="font-mono">{row.original.sl_vendor}</dd>
                                    <dt>Date</dt>
                                    <dd className="font-mono">{row.original.sl_date}</dd>
                                    <dt>Amount</dt>
                                    <dd className="font-mono">
                                      {row.original.sl_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                    </dd>
                                    {row.original.sl_ref && (
                                      <>
                                        <dt>Ref</dt>
                                        <dd className="font-mono">{row.original.sl_ref}</dd>
                                      </>
                                    )}
                                  </dl>
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
                                <Button size="sm" variant="outline" onClick={() => handleOverride(row.original.id)}>
                                  <Edit3 className="size-3.5" aria-hidden />
                                  Override Match
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

      {/* Footer CTA */}
      <div className="flex items-center justify-end border-t pt-6">
        <Button size="lg" onClick={() => navigate('/detailed-analysis')}>
          Process Updates &amp; View Detailed Analysis
          <ArrowRight className="size-4" aria-hidden />
        </Button>
      </div>
    </PageLayout>
  )
}
