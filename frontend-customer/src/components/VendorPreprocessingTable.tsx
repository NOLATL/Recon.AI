import { useState, useCallback, useRef, useEffect } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'

type NormEntry = {
  original_vendor: string
  normalized_vendor: string
  matched_to: string | null
  match_source: string
}

/** Compute the canonical Final vendor name for a given entry and optional override. */
export function computeFinalVendorName(
  entry: { original_vendor: string; matched_to: string | null; match_source: string },
  override?: string
): string {
  if (override?.trim()) return override.trim()
  if (!entry.matched_to) return entry.original_vendor
  if (entry.match_source === 'nlp' || entry.match_source === 'ai') {
    return entry.original_vendor.length <= entry.matched_to.length
      ? entry.original_vendor
      : entry.matched_to
  }
  return entry.original_vendor // preprocessing: either name normalizes the same, use GL
}

/** Display label for the Matching Process column */
function formatMethod(s: string | undefined): string {
  if (!s) return ''
  const lower = s.toLowerCase()
  if (lower === 'ai') return 'AI'
  if (lower === 'nlp') return 'Fuzzy Matching'
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}

const MATCH_WIDTH_PX = 130
const DEFAULT_WIDTHS = { gl: 20, subledger: 20, matching_process: MATCH_WIDTH_PX, override: 25, final: 35 }

interface VendorPreprocessingTableProps {
  vendorNormMap: NormEntry[]
  unmatchedSubVendors: string[]
  vendorOverrides: Record<string, string>
  onVendorOverride: (key: string, value: string) => void
}

type ColKey = 'gl' | 'subledger' | 'matching_process' | 'override' | 'final'

export function VendorPreprocessingTable({
  vendorNormMap,
  unmatchedSubVendors,
  vendorOverrides,
  onVendorOverride,
}: VendorPreprocessingTableProps) {
  const [widths, setWidths] = useState(DEFAULT_WIDTHS)
  const [resizing, setResizing] = useState<ColKey | null>(null)
  const startXRef = useRef(0)
  const startWRef = useRef(0)

  const handleResizeStart = useCallback((col: ColKey, e: React.MouseEvent) => {
    e.preventDefault()
    setResizing(col)
    startXRef.current = e.clientX
    startWRef.current = typeof widths[col] === 'number' ? (widths[col] as number) : (col === 'matching_process' ? MATCH_WIDTH_PX : 200)
  }, [widths])

  const handleResizeMove = useCallback((e: MouseEvent) => {
    if (!resizing) return
    const delta = e.clientX - startXRef.current
    const minWidth = resizing === 'matching_process' ? 100 : 120
    const newW = Math.max(minWidth, startWRef.current + delta)
    setWidths((prev) => ({ ...prev, [resizing]: newW }))
    startXRef.current = e.clientX
    startWRef.current = newW
  }, [resizing])

  const handleResizeEnd = useCallback(() => setResizing(null), [])

  useEffect(() => {
    if (!resizing) return
    const onMove = (e: MouseEvent) => handleResizeMove(e)
    const onUp = () => {
      handleResizeEnd()
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [resizing, handleResizeMove, handleResizeEnd])

  return (
    <div className="w-full overflow-hidden">
      <Table className="table-fixed">
        <colgroup>
          <col style={{ width: `${widths.gl}%` }} />
          <col style={{ width: `${widths.subledger}%` }} />
          <col style={{ width: `${widths.matching_process}px` }} />
          <col style={{ width: `${widths.override}%` }} />
          <col style={{ width: `${widths.final}%` }} />
        </colgroup>
        <TableHeader>
          <TableRow className="bg-[#333333]">
            <TableHead className="font-mono font-bold text-white bg-[#333333]">GL Source</TableHead>
            <TableHead className="font-mono font-bold text-white bg-[#333333]">Subledger Source</TableHead>
            <TableHead className="font-mono font-bold text-white bg-[#333333]" style={{ width: `${MATCH_WIDTH_PX}px` }}>Matching Process</TableHead>
            <TableHead className="font-mono font-bold text-white bg-[#333333]">Override</TableHead>
            <TableHead className="relative font-mono font-bold text-white bg-[#333333]">
              Final
              <div
                role="separator"
                aria-orientation="vertical"
                className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 transition-colors"
                onMouseDown={(e) => handleResizeStart('final', e)}
                aria-label="Resize column"
              />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vendorNormMap.map((entry) => {
            const key = entry.original_vendor
            const isUnmatched = !entry.matched_to
            const finalName = computeFinalVendorName(entry, vendorOverrides[key])
            return (
              <TableRow key={key} className={isUnmatched ? 'bg-amber-50 dark:bg-amber-950/20' : undefined}>
                <TableCell className="font-mono text-sm text-[#1a1a1a] overflow-hidden text-ellipsis" title={entry.original_vendor}>
                  {entry.original_vendor}
                </TableCell>
                <TableCell className={`font-mono text-sm overflow-hidden text-ellipsis ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`} title={entry.matched_to ?? ''}>
                  {entry.matched_to ?? '—'}
                </TableCell>
                <TableCell className={`text-xs overflow-hidden text-ellipsis ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`}>
                  {isUnmatched ? 'Unmatched' : formatMethod(entry.match_source)}
                </TableCell>
                <TableCell className="min-w-[160px]">
                  <Input
                    value={vendorOverrides[key] ?? ''}
                    onChange={(e) => onVendorOverride(key, e.target.value)}
                    className="h-8 text-sm min-w-0 w-full"
                  />
                </TableCell>
                <TableCell className={`font-mono text-sm font-medium overflow-hidden text-ellipsis ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`} title={finalName}>
                  {finalName}
                </TableCell>
              </TableRow>
            )
          })}
          {unmatchedSubVendors.map((vendor) => {
            const key = `__sub__${vendor}`
            const finalName = vendorOverrides[key]?.trim() || vendor
            return (
              <TableRow key={key} className="bg-amber-50 dark:bg-amber-950/20">
                <TableCell className="font-mono text-sm text-amber-700 dark:text-amber-400">—</TableCell>
                <TableCell className="font-mono text-sm text-[#1a1a1a] overflow-hidden text-ellipsis" title={vendor}>
                  {vendor}
                </TableCell>
                <TableCell className="text-xs text-amber-700 dark:text-amber-400">Unmatched</TableCell>
                <TableCell className="min-w-[160px]">
                  <Input
                    value={vendorOverrides[key] ?? ''}
                    onChange={(e) => onVendorOverride(key, e.target.value)}
                    className="h-8 text-sm min-w-0 w-full"
                  />
                </TableCell>
                <TableCell className="font-mono text-sm text-amber-700 dark:text-amber-400 overflow-hidden text-ellipsis" title={finalName}>
                  {finalName}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
