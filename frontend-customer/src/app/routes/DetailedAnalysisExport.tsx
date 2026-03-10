import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowRight, Loader2 } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
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
import { cn } from '@/lib/utils'
import {
  RECON_SESSION_ID_KEY,
  getConsolidation,
  runConsolidate,
  saveManualOverrides,
  type FinalConsolidationResponse,
} from '@/api/endpoints'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GlUnmatchedRow {
  id: string    // gl_id — used as Row ID reference
  entity: string
  vendor: string
  date: string
  amount: number
}

export interface SubUnmatchedRow {
  id: string    // subledger_id — used as Row ID reference
  entity: string
  vendor: string
  date: string
  amount: number
}

// ── Editable Cell ─────────────────────────────────────────────────────────────

function EditableCell({
  rowId,
  storeKey,
  persistedValues,
  onSave,
  placeholder,
}: {
  rowId: string
  storeKey: string
  persistedValues: Record<string, string>
  onSave: (rowId: string, value: string) => void
  placeholder?: string
}) {
  const committed = persistedValues[rowId] ?? ''
  const [local, setLocal] = useState(committed)
  const prevCommitted = useRef(committed)

  useEffect(() => {
    if (prevCommitted.current !== committed) {
      prevCommitted.current = committed
      setLocal(committed)
    }
  }, [committed])

  return (
    <input
      key={storeKey + '-' + rowId}
      type="text"
      value={local}
      placeholder={placeholder}
      onChange={e => setLocal(e.target.value)}
      onBlur={() => onSave(rowId, local)}
      className="w-full min-w-[90px] rounded border border-transparent bg-transparent px-1 py-0.5 text-sm hover:bg-muted/50 focus:border-input focus:bg-background focus:outline-none focus:ring-1 focus:ring-ring"
    />
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseGlRows(res: FinalConsolidationResponse): GlUnmatchedRow[] {
  return (res.residual_gl_records as Record<string, unknown>[]).map(r => ({
    id:     String(r.gl_id ?? ''),
    entity: String(r.entity ?? ''),
    vendor: String(r.vendor_name ?? r.vendor ?? ''),
    date:   String(r.transaction_date ?? r.date ?? ''),
    amount: Number(r.amount ?? 0),
  }))
}

function parseSubRows(res: FinalConsolidationResponse): SubUnmatchedRow[] {
  return (res.residual_sub_records as Record<string, unknown>[]).map(r => ({
    id:     String(r.subledger_id ?? ''),
    entity: String(r.entity ?? ''),
    vendor: String(r.vendor_name ?? r.vendor ?? ''),
    date:   String(r.transaction_date ?? r.date ?? ''),
    amount: Number(r.amount ?? 0),
  }))
}

// All summary metrics are GL-perspective only.
function computeSummary(glRows: GlUnmatchedRow[]) {
  const totalCount    = glRows.length
  const totalAmount   = glRows.reduce((s, r) => s + r.amount, 0)
  const largestAmount = glRows.length ? Math.max(...glRows.map(r => r.amount)) : 0
  const byVendor = new Map<string, number>()
  for (const r of glRows) byVendor.set(r.vendor, (byVendor.get(r.vendor) ?? 0) + r.amount)
  let topVendor = '', topVendorAmount = 0
  byVendor.forEach((sum, vendor) => { if (sum > topVendorAmount) { topVendorAmount = sum; topVendor = vendor } })
  return { totalCount, totalAmount, largestAmount, topVendor, topVendorAmount }
}

function loadFromStorage(key: string): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(key) ?? '{}') } catch { return {} }
}
function saveToStorage(key: string, data: Record<string, string>) {
  try { localStorage.setItem(key, JSON.stringify(data)) } catch { /* quota */ }
}

// Parse a comma-separated override string into an array of trimmed IDs.
function splitIds(s: string): string[] {
  return s.split(',').map(x => x.trim()).filter(Boolean)
}

const LARGE_AMOUNT_THRESHOLD = 10_000

// ── Component ─────────────────────────────────────────────────────────────────

export function DetailedAnalysisExport() {
  const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY) ?? ''
  const navigate  = useNavigate()

  useEffect(() => { window.scrollTo(0, 0) }, [])

  const [glSorting,  setGlSorting]  = useState<SortingState>([{ id: 'amount', desc: true }])
  const [subSorting, setSubSorting] = useState<SortingState>([{ id: 'amount', desc: true }])

  const [glRows,  setGlRows]  = useState<GlUnmatchedRow[]>([])
  const [subRows, setSubRows] = useState<SubUnmatchedRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [finalizing, setFinalizing] = useState(false)
  const [finalizeError, setFinalizeError] = useState<string | null>(null)

  // Notes & overrides — persisted to localStorage keyed by session
  const notesKey     = `recon-${sessionId}-notes`
  const overridesKey = `recon-${sessionId}-overrides`
  const [notes,     setNotes]     = useState<Record<string, string>>(() => loadFromStorage(notesKey))
  const [overrides, setOverrides] = useState<Record<string, string>>(() => loadFromStorage(overridesKey))

  // Debounced overrides for the "after overrides" KPI (500 ms delay so typing
  // doesn't prematurely deactivate the input while the user is still typing).
  const [debouncedOverrides, setDebouncedOverrides] = useState(overrides)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedOverrides(overrides), 500)
    return () => clearTimeout(t)
  }, [overrides])

  const saveNote = useCallback((rowId: string, value: string) => {
    setNotes(prev => {
      const next = { ...prev, [rowId]: value }
      saveToStorage(notesKey, next)
      return next
    })
  }, [notesKey])

  const saveOverride = useCallback((rowId: string, value: string, _source: 'gl' | 'sub') => {
    setOverrides(prev => {
      const prevIds = splitIds(prev[rowId] ?? '')
      const newIds  = splitIds(value)
      const added   = newIds.filter(id => !prevIds.includes(id))
      const removed = prevIds.filter(id => !newIds.includes(id))

      const next = { ...prev, [rowId]: value }

      const updatePeer = (peerId: string, ownId: string, add: boolean) => {
        const peerIds = splitIds(next[peerId] ?? '')
        if (add && !peerIds.includes(ownId)) {
          next[peerId] = [...peerIds, ownId].join(', ')
        } else if (!add) {
          next[peerId] = peerIds.filter(x => x !== ownId).join(', ')
        }
      }

      added.forEach(peerId   => updatePeer(peerId, rowId, true))
      removed.forEach(peerId => updatePeer(peerId, rowId, false))

      saveToStorage(overridesKey, next)
      return next
    })
  }, [overridesKey])

  // ── Data load ───────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    if (!sessionId) { setLoadError('No session. Start from Load Files.'); setLoading(false); return }

    const load = async (res: FinalConsolidationResponse) => {
      if (cancelled) return
      setGlRows(parseGlRows(res))
      setSubRows(parseSubRows(res))
    }

    getConsolidation(sessionId)
      .then(load)
      .catch(async err => {
        if (cancelled) return
        const status = (err as { status?: number })?.status
        if (status === 409) {
          try {
            await runConsolidate(sessionId)
            const res = await getConsolidation(sessionId)
            await load(res)
          } catch (e) {
            if (!cancelled) setLoadError(e instanceof Error ? e.message : 'Consolidation required.')
          }
        } else {
          setLoadError(err instanceof Error ? err.message : 'Failed to load unmatched records')
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [sessionId])

  // ── Before-overrides summary (uses live data) ────────────────────────────────

  const summaryBefore = useMemo(() => computeSummary(glRows), [glRows])

  // ── After-overrides summary (uses debounced overrides, 500 ms lag) ───────────

  const summaryAfter = useMemo(() => {
    // GL rows that have at least one valid Sub ID linked via override — GL perspective only.
    const overriddenGlIds = new Set(
      glRows
        .filter(r => splitIds(debouncedOverrides[r.id] ?? '').length > 0)
        .map(r => r.id)
    )
    const afterGl  = glRows.filter(r => !overriddenGlIds.has(r.id))
    const resolved = overriddenGlIds.size
    return { ...computeSummary(afterGl), resolvedCount: resolved }
  }, [glRows, debouncedOverrides])

  // ── Accept Overrides & Finalize ──────────────────────────────────────────────

  const handleFinalize = async () => {
    if (!sessionId) { setFinalizeError('No session.'); return }
    setFinalizing(true)
    setFinalizeError(null)
    try {
      // Convert localStorage overrides to {gl_id: [sub_id, ...]} — GL perspective only.
      const glOverrides: Record<string, string[]> = {}
      for (const glRow of glRows) {
        const linked = splitIds(overrides[glRow.id] ?? '')
        if (linked.length > 0) glOverrides[glRow.id] = linked
      }
      await saveManualOverrides(sessionId, glOverrides)
      navigate('/export')
    } catch (err) {
      setFinalizeError(err instanceof Error ? err.message : 'Failed to save overrides.')
    } finally {
      setFinalizing(false)
    }
  }

  // ── GL table columns ────────────────────────────────────────────────────────

  const glColumns = useMemo<ColumnDef<GlUnmatchedRow, unknown>[]>(
    () => [
      {
        accessorKey: 'id',
        header: 'Row ID',
        cell: c => <span className="font-mono text-xs text-muted-foreground">{String(c.getValue())}</span>,
        enableSorting: false,
      },
      { accessorKey: 'entity', header: 'Entity',  cell: c => c.getValue(), enableSorting: false },
      { accessorKey: 'vendor', header: 'Vendor',  cell: c => c.getValue(), enableSorting: false },
      { accessorKey: 'date',   header: 'Date',    cell: c => c.getValue() },
      {
        accessorKey: 'amount',
        header: 'Amount',
        cell: c => Number(c.getValue()).toLocaleString(undefined, { minimumFractionDigits: 2 }),
      },
      {
        id: 'notes',
        header: 'Notes',
        enableSorting: false,
        cell: ({ row }) => (
          <EditableCell
            rowId={row.original.id}
            storeKey="gl-notes"
            persistedValues={notes}
            onSave={saveNote}
            placeholder="Add note…"
          />
        ),
      },
      {
        id: 'override',
        header: 'Override (Sub IDs)',
        enableSorting: false,
        cell: ({ row }) => (
          <EditableCell
            rowId={row.original.id}
            storeKey="gl-overrides"
            persistedValues={overrides}
            onSave={(rowId, v) => saveOverride(rowId, v, 'gl')}
            placeholder="e.g. SUB-001, SUB-002"
          />
        ),
      },
    ],
    [notes, overrides, saveNote, saveOverride]
  )

  // ── Sub table columns ───────────────────────────────────────────────────────

  const subColumns = useMemo<ColumnDef<SubUnmatchedRow, unknown>[]>(
    () => [
      {
        accessorKey: 'id',
        header: 'Row ID',
        cell: c => <span className="font-mono text-xs text-muted-foreground">{String(c.getValue())}</span>,
        enableSorting: false,
      },
      { accessorKey: 'entity', header: 'Entity',  cell: c => c.getValue(), enableSorting: false },
      { accessorKey: 'vendor', header: 'Vendor',  cell: c => c.getValue(), enableSorting: false },
      { accessorKey: 'date',   header: 'Date',    cell: c => c.getValue() },
      {
        accessorKey: 'amount',
        header: 'Amount',
        cell: c => Number(c.getValue()).toLocaleString(undefined, { minimumFractionDigits: 2 }),
      },
      {
        id: 'notes',
        header: 'Notes',
        enableSorting: false,
        cell: ({ row }) => (
          <EditableCell
            rowId={row.original.id}
            storeKey="sub-notes"
            persistedValues={notes}
            onSave={saveNote}
            placeholder="Add note…"
          />
        ),
      },
      {
        id: 'override',
        header: 'Override (GL IDs)',
        enableSorting: false,
        cell: ({ row }) => (
          <EditableCell
            rowId={row.original.id}
            storeKey="sub-overrides"
            persistedValues={overrides}
            onSave={(rowId, v) => saveOverride(rowId, v, 'sub')}
            placeholder="e.g. GL-001, GL-002"
          />
        ),
      },
    ],
    [notes, overrides, saveNote, saveOverride]
  )

  // ── Tables ──────────────────────────────────────────────────────────────────

  const glTable = useReactTable({
    data: glRows,
    columns: glColumns,
    state: { sorting: glSorting },
    onSortingChange: setGlSorting,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  })

  const subTable = useReactTable({
    data: subRows,
    columns: subColumns,
    state: { sorting: subSorting },
    onSortingChange: setSubSorting,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  })

  // ── Shared table renderer ───────────────────────────────────────────────────

  function UnmatchedTable<T extends { id: string; amount: number }>({
    tableInstance,
  }: {
    tableInstance: ReturnType<typeof useReactTable<T>>
  }) {
    return (
      <>
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              {tableInstance.getHeaderGroups().map(hg => (
                <TableRow key={hg.id}>
                  {hg.headers.map(header => (
                    <TableHead key={header.id} className="whitespace-nowrap bg-muted/50">
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={() => header.column.toggleSorting(header.column.getIsSorted() === 'asc')}
                          className="flex items-center gap-1 font-medium hover:text-foreground"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {header.column.getIsSorted() === 'asc'  && ' ↑'}
                          {header.column.getIsSorted() === 'desc' && ' ↓'}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {tableInstance.getRowModel().rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={99} className="py-6 text-center text-sm text-muted-foreground">
                    No records.
                  </TableCell>
                </TableRow>
              ) : (
                tableInstance.getRowModel().rows.map(row => (
                  <TableRow
                    key={row.id}
                    className={cn(row.original.amount >= LARGE_AMOUNT_THRESHOLD && 'bg-amber-500/10')}
                  >
                    {row.getVisibleCells().map(cell => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Page {tableInstance.getState().pagination.pageIndex + 1} of {tableInstance.getPageCount()}
          </p>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm"
              onClick={() => tableInstance.previousPage()}
              disabled={!tableInstance.getCanPreviousPage()}>Previous</Button>
            <Button variant="outline" size="sm"
              onClick={() => tableInstance.nextPage()}
              disabled={!tableInstance.getCanNextPage()}>Next</Button>
          </div>
        </div>
      </>
    )
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <PageLayout title="Unmatched Analysis" description="Summary of unmatched transactions before Overrides entered below.">

      {/* 1. Before-overrides KPI cards */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loadError && <p className="col-span-full text-sm text-destructive">{loadError}</p>}
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Unmatched Transactions</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : summaryBefore.totalCount.toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Unmatched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : `$${summaryBefore.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Largest Unmatched Transaction</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : `$${summaryBefore.largestAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Vendor Concentration</p>
            <p className="mt-1 text-lg font-semibold text-foreground">
              {loading ? '—' : summaryBefore.topVendor || '—'}
            </p>
            <p className="mt-0.5 text-sm tabular-nums text-muted-foreground">
              {loading ? '—' : `$${summaryBefore.topVendorAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })} unmatched`}
            </p>
          </CardContent>
        </Card>
      </section>

      {/* 2a. GL Unmatched Records */}
      <Card>
        <CardHeader>
          <CardTitle>GL Unmatched Records</CardTitle>
          <CardDescription>
            General Ledger rows with no match. Enter Subledger Row ID(s) in the Override column to manually link records;
            use commas for many-to-one.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Loading…
            </div>
          ) : (
            <UnmatchedTable tableInstance={glTable} />
          )}
        </CardContent>
      </Card>

      {/* 2b. Subledger Unmatched Records */}
      <Card>
        <CardHeader>
          <CardTitle>Subledger Unmatched Records</CardTitle>
          <CardDescription>
            Subledger rows with no match. Enter GL Row ID(s) in the Override column to manually link records;
            use commas for many-to-one.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Loading…
            </div>
          ) : (
            <UnmatchedTable tableInstance={subTable} />
          )}
        </CardContent>
      </Card>

      {/* 3. After-overrides KPI cards (debounced real-time) */}
      <section>
        <p className="mb-3 text-sm font-medium text-muted-foreground">
          Summary of final unmatched transactions after Overrides.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Remaining Unmatched</p>
              <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
                {loading ? '—' : summaryAfter.totalCount.toLocaleString()}
              </p>
              {summaryAfter.resolvedCount > 0 && (
                <p className="mt-0.5 text-xs text-green-600 dark:text-green-500">
                  {summaryAfter.resolvedCount} resolved via override
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Remaining GL Amount</p>
              <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
                {loading ? '—' : `$${summaryAfter.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Largest Remaining</p>
              <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
                {loading ? '—' : `$${summaryAfter.largestAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Remaining Vendor</p>
              <p className="mt-1 text-lg font-semibold text-foreground">
                {loading ? '—' : summaryAfter.topVendor || '—'}
              </p>
              <p className="mt-0.5 text-sm tabular-nums text-muted-foreground">
                {loading ? '—' : `$${summaryAfter.topVendorAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })} unmatched`}
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* 4. Accept Overrides & Finalize */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-4">
            <Button size="lg" onClick={handleFinalize} disabled={finalizing}>
              {finalizing ? (
                <><Loader2 className="size-4 animate-spin" aria-hidden />Saving…</>
              ) : (
                <>Accept Overrides &amp; Finalize<ArrowRight className="size-4" aria-hidden /></>
              )}
            </Button>
            {summaryAfter.resolvedCount > 0 && (
              <p className="text-sm text-muted-foreground">
                {summaryAfter.resolvedCount} manual override(s) will be included in the export.
              </p>
            )}
          </div>
          {finalizeError && <p className="mt-2 text-sm text-destructive">{finalizeError}</p>}
        </CardContent>
      </Card>

    </PageLayout>
  )
}
