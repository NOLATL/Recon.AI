/**
 * Shared download utilities — xlsx (multi-sheet) and CSV (single sheet).
 *
 * All step components import from here to keep download logic DRY and
 * to ensure consistent filename conventions across the app.
 */

import * as XLSX from 'xlsx'

export interface DownloadSheet {
  /** Tab label inside the Excel workbook (max 31 chars — enforced automatically). */
  name: string
  /** Flat row objects; keys become column headers. */
  rows: Record<string, unknown>[]
}

/** Write a multi-sheet Excel workbook and trigger a browser download. */
export function downloadXlsx(sheets: DownloadSheet[], filename: string): void {
  const wb = XLSX.utils.book_new()
  for (const sheet of sheets) {
    const ws =
      sheet.rows.length > 0
        ? XLSX.utils.json_to_sheet(sheet.rows)
        : XLSX.utils.aoa_to_sheet([[]])
    XLSX.utils.book_append_sheet(wb, ws, sheet.name.slice(0, 31))
  }
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`)
}

/** Write a single-sheet CSV and trigger a browser download. */
export function downloadCsv(rows: Record<string, unknown>[], filename: string): void {
  if (rows.length === 0) return
  const headers = Object.keys(rows[0])
  const escape = (v: unknown): string => {
    const s = v == null ? '' : String(v)
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"`
      : s
  }
  const csv = [
    headers.join(','),
    ...rows.map((r) => headers.map((h) => escape(r[h])).join(',')),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
