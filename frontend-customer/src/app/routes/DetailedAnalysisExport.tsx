import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { Download, Loader2 } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
  runExport,
  getExportManifest,
  getExportZipUrl,
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

/**
 * Single-line editable input that keeps itself active while the user types.
 * The parent state is only updated on blur (commit), so intermediate keystrokes
 * never cause the input to lose focus due to re-renders.
 */
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

  // Sync only when the persisted value changes from outside (initial load)
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

function computeGlSummary(rows: GlUnmatchedRow[]) {
  const totalCount  = rows.length
  const totalAmount = rows.reduce((s, r) => s + r.amount, 0)
  const largestAmount = rows.length ? Math.max(...rows.map(r => r.amount)) : 0
  const byVendor = new Map<string, number>()
  for (const r of rows) byVendor.set(r.vendor, (byVendor.get(r.vendor) ?? 0) + r.amount)
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

const LARGE_AMOUNT_THRESHOLD = 10_000

const EXPORT_ARTIFACTS = [
  { id: 'gl',         label: 'Uploaded GL Data',                    group: 'data' as const },
  { id: 'subledger',  label: 'Uploaded Subledger Data',             group: 'data' as const },
  { id: 'preprocess', label: 'Preprocessing Output',                group: 'data' as const },
  { id: 'det_in_out', label: 'Deterministic Matching Input/Output', group: 'data' as const },
  { id: 'prob_in_out',label: 'Probabilistic Matching Input/Output', group: 'data' as const },
  { id: 'ai_in_out',  label: 'AI Matching Input/Output',            group: 'data' as const },
  { id: 'final',      label: 'Final Results After Overrides',       group: 'data' as const },
  { id: 'residual',   label: 'Residual Unmatched Transactions',     group: 'data' as const },
  { id: 'rejected',   label: 'Rejected Matches',                    group: 'data' as const },
  { id: 'log',        label: 'Process Log',                         group: 'data' as const },
  { id: 'pdf',        label: 'Executive Summary PDF',               group: 'narrative' as const },
] as const

// Maps each artifact ID to the filenames it produces in the export manifest.
const ARTIFACT_FILES: Record<string, string[]> = {
  gl:         ['uploaded_gl.csv'],
  subledger:  ['uploaded_subledger.csv'],
  preprocess: ['preprocessing_output.csv'],
  det_in_out: ['deterministic_matches.csv'],
  prob_in_out:['probabilistic_matches.csv'],
  ai_in_out:  ['ai_matches.csv'],
  final:      ['final_results.csv'],
  residual:   ['residual_unmatched_gl.csv', 'residual_unmatched_sub.csv'],
  rejected:   ['rejected_matches.csv'],
  log:        ['process_log_run.csv', 'process_log_steps.csv', 'process_log_ai.csv'],
  pdf:        ['reconciliation_report.pdf'],
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DetailedAnalysisExport() {
  const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY) ?? ''

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  const [glSorting,  setGlSorting]  = useState<SortingState>([{ id: 'amount', desc: true }])
  const [subSorting, setSubSorting] = useState<SortingState>([{ id: 'amount', desc: true }])

  const [selectedArtifacts, setSelectedArtifacts] = useState<Set<string>>(new Set())

  const [glRows,  setGlRows]  = useState<GlUnmatchedRow[]>([])
  const [subRows, setSubRows] = useState<SubUnmatchedRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [exportLoading, setExportLoading] = useState(false)
  const [exportError,   setExportError]   = useState<string | null>(null)

  // Notes & overrides — persisted to localStorage keyed by session
  const notesKey     = `recon-${sessionId}-notes`
  const overridesKey = `recon-${sessionId}-overrides`
  const [notes,     setNotes]     = useState<Record<string, string>>(() => loadFromStorage(notesKey))
  const [overrides, setOverrides] = useState<Record<string, string>>(() => loadFromStorage(overridesKey))

  const saveNote = useCallback((rowId: string, value: string) => {
    setNotes(prev => {
      const next = { ...prev, [rowId]: value }
      saveToStorage(notesKey, next)
      return next
    })
  }, [notesKey])

  /**
   * Save an override value and keep the other table in sync.
   * source='gl'  → rowId is a GL row, value contains Sub IDs
   * source='sub' → rowId is a Sub row, value contains GL IDs
   */
  const saveOverride = useCallback((rowId: string, value: string, source: 'gl' | 'sub') => {
    setOverrides(prev => {
      const split = (s: string) => s.split(',').map(x => x.trim()).filter(Boolean)
      const prevIds = split(prev[rowId] ?? '')
      const newIds  = split(value)

      const added   = newIds.filter(id => !prevIds.includes(id))
      const removed = prevIds.filter(id => !newIds.includes(id))

      const next = { ...prev, [rowId]: value }

      // For each newly linked peer, add this row's ID to the peer's override list.
      // For each de-linked peer, remove this row's ID from the peer's override list.
      const updatePeer = (peerId: string, ownId: string, add: boolean) => {
        const peerIds = split(next[peerId] ?? '')
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

  // ── Summary ─────────────────────────────────────────────────────────────────

  const summary = useMemo(() => computeGlSummary(glRows), [glRows])

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

  // ── Export ──────────────────────────────────────────────────────────────────

  const toggleArtifact = (id: string) => {
    setSelectedArtifacts(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    const allIds = EXPORT_ARTIFACTS.map(a => a.id)
    setSelectedArtifacts(new Set(allIds))
  }

  const selectAllData = () => {
    const dataIds = EXPORT_ARTIFACTS.filter(a => a.group === 'data').map(a => a.id)
    setSelectedArtifacts(prev => { const next = new Set(prev); dataIds.forEach(id => next.add(id)); return next })
  }

  const handleDownload = async () => {
    if (!sessionId) { setExportError('No session.'); return }
    if (selectedArtifacts.size === 0) { setExportError('Select at least one item to export.'); return }
    setExportLoading(true)
    setExportError(null)
    try {
      try { await runExport(sessionId) } catch (e) {
        if ((e as { status?: number })?.status !== 409) throw e
      }
      const manifest = await getExportManifest(sessionId)

      // Build the ordered list of filenames requested by selected checkboxes.
      const requested = new Set<string>()
      for (const artifactId of selectedArtifacts) {
        for (const filename of ARTIFACT_FILES[artifactId] ?? []) {
          requested.add(filename)
        }
      }

      const filenames = manifest.files
        .filter(f => requested.has(f.filename))
        .map(f => f.filename)

      if (filenames.length === 0) {
        setExportError('None of the selected items are available in the export manifest.')
        return
      }

      // Trigger a single ZIP download — avoids popup-blocker issues with multiple window.open calls.
      const a = document.createElement('a')
      a.href = getExportZipUrl(sessionId, filenames)
      a.download = ''
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExportLoading(false)
    }
  }

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
    <PageLayout title="Detailed Analysis" description="Unmatched transactions and export reconciliation package.">

      {/* 1. GL-perspective summary KPI cards (4) */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {loadError && <p className="col-span-full text-sm text-destructive">{loadError}</p>}
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Unmatched Transactions</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : summary.totalCount.toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Unmatched Amount</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : `$${summary.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Largest Unmatched Transaction</p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {loading ? '—' : `$${summary.largestAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Top Vendor Concentration</p>
            <p className="mt-1 text-lg font-semibold text-foreground">
              {loading ? '—' : summary.topVendor || '—'}
            </p>
            <p className="mt-0.5 text-sm tabular-nums text-muted-foreground">
              {loading ? '—' : `$${summary.topVendorAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })} unmatched`}
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

      {/* 3. Export Builder */}
      <Card>
        <CardHeader>
          <CardTitle>Export Reconciliation Package</CardTitle>
          <CardDescription>
            Choose which artifacts to include. Download produces a single ZIP file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={selectAll}>
              Select all
            </Button>
            <Button variant="outline" size="sm" onClick={selectAllData}>
              Select all data sets
            </Button>
            <Button variant="outline" size="sm" onClick={() => setSelectedArtifacts(new Set())}>
              Clear
            </Button>
          </div>
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Data sets</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter(a => a.group === 'data').map(artifact => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label htmlFor={artifact.id} className="cursor-pointer text-sm text-foreground">
                      {artifact.label}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Narrative</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter(a => a.group === 'narrative').map(artifact => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label htmlFor={artifact.id} className="cursor-pointer text-sm text-foreground">
                      {artifact.label}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="border-t pt-4">
            <Button onClick={handleDownload} size="lg" disabled={exportLoading}>
              {exportLoading ? (
                <><Loader2 className="size-4 animate-spin" aria-hidden />Exporting…</>
              ) : (
                <><Download className="size-4" aria-hidden />Download Export Package</>
              )}
            </Button>
            {exportError && <p className="mt-2 text-sm text-destructive">{exportError}</p>}
            {selectedArtifacts.size > 0 && (
              <p className="mt-2 text-sm text-muted-foreground">
                {selectedArtifacts.size} item(s) selected for export.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </PageLayout>
  )
}
