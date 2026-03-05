import { useState, useMemo, useEffect } from 'react'
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
  getExportFileDownloadUrl,
  consolidationToUnmatched,
  type UnmatchedRecord,
} from '@/api/endpoints'

export interface UnmatchedRow {
  id: string
  entity: string
  vendor: string
  date: string
  amount: number
  notes?: string
}

function toUnmatchedRow(r: UnmatchedRecord, index: number): UnmatchedRow {
  return {
    id: String(index + 1),
    entity: r.entity,
    vendor: r.vendor,
    date: r.date,
    amount: r.amount,
  }
}

function computeUnmatchedSummary(rows: UnmatchedRow[]) {
  const totalCount = rows.length
  const largestAmount = rows.length ? Math.max(...rows.map((r) => r.amount)) : 0
  const byVendor = new Map<string, number>()
  for (const r of rows) {
    byVendor.set(r.vendor, (byVendor.get(r.vendor) ?? 0) + r.amount)
  }
  let topVendor = ''
  let topVendorAmount = 0
  byVendor.forEach((sum, vendor) => {
    if (sum > topVendorAmount) {
      topVendorAmount = sum
      topVendor = vendor
    }
  })
  return { totalCount, largestAmount, topVendor, topVendorAmount }
}

const LARGE_AMOUNT_THRESHOLD = 10000

const EXPORT_ARTIFACTS = [
  { id: 'gl', label: 'Uploaded GL Data', group: 'data' as const },
  { id: 'subledger', label: 'Uploaded Subledger Data', group: 'data' as const },
  { id: 'preprocess', label: 'Preprocessing Output', group: 'data' as const },
  { id: 'det_in_out', label: 'Deterministic Matching Input/Output', group: 'data' as const },
  { id: 'prob_in_out', label: 'Probabilistic Matching Input/Output', group: 'data' as const },
  { id: 'ai_in_out', label: 'AI Matching Input/Output', group: 'data' as const },
  { id: 'final', label: 'Final Results After Overrides', group: 'data' as const },
  { id: 'residual', label: 'Residual Unmatched Transactions', group: 'data' as const },
  { id: 'log', label: 'Processing Log', group: 'data' as const },
  { id: 'pdf', label: 'Executive Summary PDF', group: 'narrative' as const },
] as const

export function DetailedAnalysisExport() {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'amount', desc: true }])
  const [selectedArtifacts, setSelectedArtifacts] = useState<Set<string>>(new Set())
  const [unmatched, setUnmatched] = useState<UnmatchedRow[]>([])
  const [unmatchedLoading, setUnmatchedLoading] = useState(true)
  const [unmatchedError, setUnmatchedError] = useState<string | null>(null)
  const [exportLoading, setExportLoading] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY)
    setUnmatchedLoading(true)
    setUnmatchedError(null)
    if (!sessionId) {
      setUnmatchedError('No session. Start from Load Files.')
      setUnmatchedLoading(false)
      return
    }
    getConsolidation(sessionId)
      .then((res) => {
        if (cancelled) return
        const list = consolidationToUnmatched(res)
        setUnmatched(list.map((r, i) => toUnmatchedRow(r, i)))
      })
      .catch(async (err) => {
        if (cancelled) return
        const status = (err as { status?: number })?.status
        if (status === 409) {
          try {
            await runConsolidate(sessionId)
            const res = await getConsolidation(sessionId)
            if (!cancelled) {
              const list = consolidationToUnmatched(res)
              setUnmatched(list.map((r, i) => toUnmatchedRow(r, i)))
            }
          } catch (e) {
            if (!cancelled) setUnmatchedError(e instanceof Error ? e.message : 'Consolidation required.')
          }
        } else {
          setUnmatchedError(err instanceof Error ? err.message : 'Failed to load unmatched')
        }
      })
      .finally(() => {
        if (!cancelled) setUnmatchedLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const summary = useMemo(() => computeUnmatchedSummary(unmatched), [unmatched])

  const toggleArtifact = (id: string) => {
    setSelectedArtifacts((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectAllData = () => {
    const dataIds = EXPORT_ARTIFACTS.filter((a) => a.group === 'data').map((a) => a.id)
    setSelectedArtifacts((prev) => {
      const next = new Set(prev)
      dataIds.forEach((id) => next.add(id))
      return next
    })
  }

  const handleDownload = async () => {
    const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (!sessionId) {
      setExportError('No session.')
      return
    }
    setExportLoading(true)
    setExportError(null)
    try {
      try {
        await runExport(sessionId)
      } catch (e) {
        const status = (e as { status?: number })?.status
        if (status !== 409) throw e
        // Already finalized — continue to get manifest
      }
      const manifest = await getExportManifest(sessionId)
      manifest.files.forEach((f) => {
        window.open(getExportFileDownloadUrl(sessionId, f.filename), '_blank')
      })
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExportLoading(false)
    }
  }

  const columns = useMemo<ColumnDef<UnmatchedRow, unknown>[]>(
    () => [
      {
        accessorKey: 'entity',
        header: 'Entity',
        cell: (c) => c.getValue(),
        enableSorting: false,
      },
      {
        accessorKey: 'vendor',
        header: 'Vendor',
        cell: (c) => c.getValue(),
        enableSorting: false,
      },
      {
        accessorKey: 'date',
        header: 'Date',
        cell: (c) => c.getValue(),
      },
      {
        accessorKey: 'amount',
        header: 'Amount',
        cell: (c) => {
          const value = Number(c.getValue())
          return value.toLocaleString(undefined, { minimumFractionDigits: 2 })
        },
      },
      {
        accessorKey: 'notes',
        header: 'Notes',
        cell: (c) => c.getValue() ?? '—',
        enableSorting: false,
      },
    ],
    []
  )

  const table = useReactTable({
    data: unmatched,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    initialState: { pagination: { pageSize: 5 } },
  })


  return (
    <PageLayout title="Detailed Analysis" description="Unmatched transactions and export reconciliation package.">
      {/* 1. Unmatched Summary Cards */}
      <section className="grid gap-4 sm:grid-cols-3">
        {unmatchedError && (
          <p className="col-span-full text-sm text-destructive">{unmatchedError}</p>
        )}
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Total Unmatched Transactions
            </p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {unmatchedLoading ? '—' : summary.totalCount.toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Largest Unmatched Transaction
            </p>
            <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight text-foreground">
              {unmatchedLoading ? '—' : `$${summary.largestAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Top Vendor Concentration
            </p>
            <p className="mt-1 text-lg font-semibold text-foreground">
              {unmatchedLoading ? '—' : summary.topVendor || '—'}
            </p>
            <p className="mt-0.5 text-sm tabular-nums text-muted-foreground">
              {unmatchedLoading ? '—' : `$${summary.topVendorAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })} unmatched`}
            </p>
          </CardContent>
        </Card>
      </section>

      {/* 2. Unmatched Transactions Table */}
      <Card>
        <CardHeader>
          <CardTitle>Unmatched Transactions</CardTitle>
          <CardDescription>
            Review unmatched records. Sort by amount or date; large transactions are highlighted.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id} className="whitespace-nowrap">
                        {header.column.getCanSort() ? (
                          <button
                            type="button"
                            onClick={() => header.column.toggleSorting(header.column.getIsSorted() === 'asc')}
                            className="flex items-center gap-1 font-medium hover:text-foreground"
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {header.column.getIsSorted() === 'asc' && ' ↑'}
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
                {table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className={cn(
                      row.original.amount >= LARGE_AMOUNT_THRESHOLD &&
                        'bg-amber-500/10 dark:bg-amber-500/5'
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              Page {table.getState().pagination.pageIndex + 1} of{' '}
              {table.getPageCount()}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                Next
              </Button>
            </div>
          </div>
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
            <Button variant="outline" size="sm" onClick={selectAllData}>
              Select all data sets
            </Button>
          </div>
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Data sets</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter((a) => a.group === 'data').map((artifact) => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label
                      htmlFor={artifact.id}
                      className="cursor-pointer text-sm text-foreground"
                    >
                      {artifact.label}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Narrative</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter((a) => a.group === 'narrative').map((artifact) => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label
                      htmlFor={artifact.id}
                      className="cursor-pointer text-sm text-foreground"
                    >
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
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Exporting…
                </>
              ) : (
                <>
                  <Download className="size-4" aria-hidden />
                  Download Export Package
                </>
              )}
            </Button>
            {exportError && (
              <p className="mt-2 text-sm text-destructive">{exportError}</p>
            )}
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
