import { useState, useCallback, useRef, useEffect } from 'react'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'

type NormEntry = {
  original_vendor: string
  normalized_vendor: string
  matched_to: string | null
  match_source: string
}

/** Display "AI" instead of "ai" or "Ai" */
function formatMethod(s: string | undefined): string {
  if (!s) return ''
  if (s.toLowerCase() === 'ai') return 'AI'
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
}

/** Method column fixed at 100px; others in % (must sum to 100 for the 4 % cols, method is extra) */
const METHOD_WIDTH_PX = 100
const DEFAULT_WIDTHS = { gl: 20, subledger: 20, standardized: 25, method: METHOD_WIDTH_PX, override: 35 }

interface VendorPreprocessingTableProps {
  vendorNormMap: NormEntry[]
  unmatchedSubVendors: string[]
  unmatchedSubNormalized: Record<string, string>
  vendorOverrides: Record<string, string>
  onVendorOverride: (key: string, value: string) => void
}

type ColKey = 'gl' | 'subledger' | 'standardized' | 'method' | 'override'

export function VendorPreprocessingTable({
  vendorNormMap,
  unmatchedSubVendors,
  unmatchedSubNormalized,
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
    startWRef.current = typeof widths[col] === 'number' ? (widths[col] as number) : (col === 'method' ? METHOD_WIDTH_PX : 200)
  }, [widths])

  const handleResizeMove = useCallback((e: MouseEvent) => {
    if (!resizing) return
    const delta = e.clientX - startXRef.current
    const minWidth = resizing === 'method' ? 80 : 120
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
          <col style={{ width: `${widths.standardized}%` }} />
          <col style={{ width: `${widths.method}px` }} />
          <col style={{ width: `${widths.override}%` }} />
        </colgroup>
        <TableHeader>
          <TableRow className="bg-[#333333]">
            <TableHead className="font-mono font-bold text-white bg-[#333333]">GL Vendor (Input)</TableHead>
            <TableHead className="font-mono font-bold text-white bg-[#333333]">Subledger Vendor (Input)</TableHead>
            <TableHead className="font-mono font-bold text-white bg-[#333333]">Standardized Vendor Name</TableHead>
            <TableHead className="w-[100px] font-mono font-bold text-white bg-[#333333]">Method</TableHead>
            <TableHead className="relative min-w-[200px] font-mono font-bold text-white bg-[#333333]">
              Override
              <div
                role="separator"
                aria-orientation="vertical"
                className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 transition-colors"
                onMouseDown={(e) => handleResizeStart('override', e)}
                aria-label="Resize column"
              />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vendorNormMap.map((entry) => {
            const key = entry.original_vendor
            const isUnmatched = !entry.matched_to
            const effective = vendorOverrides[key] || entry.normalized_vendor
            return (
              <TableRow key={key} className={isUnmatched ? 'bg-amber-50 dark:bg-amber-950/20' : undefined}>
                <TableCell className="font-mono text-sm text-[#1a1a1a] overflow-hidden text-ellipsis" title={entry.original_vendor}>
                  {entry.original_vendor}
                </TableCell>
                <TableCell className={`font-mono text-sm overflow-hidden text-ellipsis ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`} title={entry.matched_to ?? ''}>
                  {entry.matched_to ?? '—'}
                </TableCell>
                <TableCell className={`font-mono text-sm font-medium overflow-hidden text-ellipsis ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`} title={effective}>
                  {effective}
                </TableCell>
                <TableCell className={`text-xs overflow-hidden text-ellipsis w-[100px] min-w-[100px] ${isUnmatched ? 'text-amber-700 dark:text-amber-400' : 'text-[#1a1a1a]'}`}>
                  {isUnmatched ? 'unmatched' : formatMethod(entry.match_source)}
                </TableCell>
                <TableCell className="min-w-[200px]">
                  <Input
                    placeholder={entry.normalized_vendor}
                    value={vendorOverrides[key] ?? ''}
                    onChange={(e) => onVendorOverride(key, e.target.value)}
                    className="h-8 text-sm min-w-0 w-full"
                  />
                </TableCell>
              </TableRow>
            )
          })}
          {unmatchedSubVendors.map((vendor) => {
            const key = `__sub__${vendor}`
            const normalizedName = unmatchedSubNormalized[vendor] ?? vendor
            return (
              <TableRow key={key} className="bg-amber-50 dark:bg-amber-950/20">
                <TableCell className="font-mono text-sm text-amber-700 dark:text-amber-400">—</TableCell>
                <TableCell className="font-mono text-sm text-[#1a1a1a] overflow-hidden text-ellipsis" title={vendor}>
                  {vendor}
                </TableCell>
                <TableCell className="font-mono text-sm text-amber-700 dark:text-amber-400 overflow-hidden text-ellipsis">
                  {normalizedName !== vendor ? normalizedName : '(unmatched)'}
                </TableCell>
                <TableCell className="text-xs text-amber-700 dark:text-amber-400 w-[100px]">unmatched</TableCell>
                <TableCell className="min-w-[200px]">
                  <Input
                    placeholder={normalizedName}
                    value={vendorOverrides[key] ?? normalizedName}
                    onChange={(e) => onVendorOverride(key, e.target.value)}
                    className="h-8 text-sm min-w-0 w-full"
                  />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
