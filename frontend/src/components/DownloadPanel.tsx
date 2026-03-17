/**
 * DownloadPanel — reusable checkbox-selector + "Download Selected (.xlsx)" button.
 *
 * Usage:
 *   <DownloadPanel
 *     filename={`det_review_${sessionId.slice(0, 8)}`}
 *     sheets={[
 *       { id: 'matches', label: 'Matched Records', name: 'Matches', rows: matchRows },
 *       { id: 'gl',      label: 'GL Input',        name: 'GL Input', rows: glRows },
 *     ]}
 *   />
 *
 * All sheets are selected by default. The user can deselect any subset.
 * The "Download Selected" button is disabled when nothing is checked.
 */

import { useState } from 'react'
import { downloadXlsx, type DownloadSheet } from '@/utils/download'

export interface PanelSheet extends DownloadSheet {
  /** Unique key used for checkbox state — must be stable across renders. */
  id: string
  /** Human-readable label shown next to the checkbox. */
  label: string
}

interface Props {
  sheets: PanelSheet[]
  /** File stem — `.xlsx` is appended automatically. */
  filename: string
}

function DownloadIcon() {
  return (
    <svg
      className="w-3.5 h-3.5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
      />
    </svg>
  )
}

export default function DownloadPanel({ sheets, filename }: Props) {
  const [selected, setSelected] = useState<Record<string, boolean>>(
    () => Object.fromEntries(sheets.map((s) => [s.id, true])),
  )

  const toggle = (id: string) =>
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }))

  const setAll = (v: boolean) =>
    setSelected(Object.fromEntries(sheets.map((s) => [s.id, v])))

  const activeSheets = sheets.filter((s) => selected[s.id])

  const handleDownload = () => {
    if (activeSheets.length === 0) return
    downloadXlsx(
      activeSheets.map((s) => ({ name: s.name, rows: s.rows })),
      filename,
    )
  }

  return (
    <div className="border border-void-border rounded-xl p-4 bg-void-elevated">
      <div className="flex items-center justify-between mb-3">
        <h5 className="data-label">Export Data</h5>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setAll(true)}
            className="text-bdo-red-light hover:text-bdo-red transition-colors"
          >
            Select all
          </button>
          <span className="text-white/20">|</span>
          <button onClick={() => setAll(false)} className="text-white/40 hover:text-white/60 transition-colors">
            None
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-2.5 mb-4">
        {sheets.map((s) => (
          <label key={s.id} className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={selected[s.id] ?? false}
              onChange={() => toggle(s.id)}
              className="w-3.5 h-3.5 rounded border-void-border accent-bdo-red cursor-pointer"
            />
            <span className="text-sm text-white/70">{s.label}</span>
            <span className="text-xs text-white/35">
              ({s.rows.length.toLocaleString()} rows)
            </span>
          </label>
        ))}
      </div>

      <button
        onClick={handleDownload}
        disabled={activeSheets.length === 0}
        className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
      >
        <DownloadIcon />
        Download Selected ({activeSheets.length} sheet
        {activeSheets.length !== 1 ? 's' : ''}) (.xlsx)
      </button>
    </div>
  )
}
