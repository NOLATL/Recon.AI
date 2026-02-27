import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { runExport } from '@/api/endpoints'
import type { ExportResponse, ExportFile } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function ExportFileRow({ file }: { file: ExportFile }) {
  const [copied, setCopied] = useState(false)

  const copyPath = () => {
    navigator.clipboard.writeText(file.path).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const isPdf = file.filename.endsWith('.pdf')

  return (
    <div className="border border-gray-200 rounded-md p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900">{file.filename}</span>
            <span
              className={[
                'text-xs px-1.5 py-0.5 rounded font-medium',
                isPdf ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600',
              ].join(' ')}
            >
              {isPdf ? 'PDF' : 'CSV'}
            </span>
          </div>
          <p className="text-xs font-mono text-gray-500 mt-1 truncate">{file.path}</p>
          <div className="flex gap-4 mt-1.5 text-xs text-gray-400">
            <span>{formatBytes(file.size_bytes)}</span>
            <span className="font-mono truncate max-w-[200px]" title={file.sha256}>
              SHA256: {file.sha256.slice(0, 16)}…
            </span>
          </div>
        </div>
        <button
          onClick={copyPath}
          className="flex-shrink-0 text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-md transition-colors"
        >
          {copied ? '✓ Copied' : 'Copy path'}
        </button>
      </div>
    </div>
  )
}

const FILE_DESCRIPTIONS: Record<string, string> = {
  'final_matches.csv': 'All accepted matches across all layers',
  'residual_unmatched_gl.csv': 'GL records with no match found',
  'residual_unmatched_sub.csv': 'Subledger records with no match found',
  'rejected_matches.csv': 'All human-rejected match candidates',
  'audit_log.csv': 'Complete audit trail of all decisions and transitions',
  'reconciliation_report.pdf': 'Executive summary and statistics',
}

function ExportResult({ data }: { data: ExportResponse }) {
  const totalSize = data.files.reduce((sum, f) => sum + f.size_bytes, 0)

  return (
    <div className="mt-6 space-y-4">
      <div className="bg-green-50 border border-green-200 rounded-md p-4">
        <p className="text-sm font-medium text-green-800 mb-2">Export complete!</p>
        <div className="text-sm text-green-700 space-y-1">
          <p>
            <strong>Export directory:</strong>{' '}
            <span className="font-mono">{data.export_dir}</span>
          </p>
          <p>
            <strong>Exported at:</strong> {new Date(data.exported_at).toLocaleString()}
          </p>
          <p>
            <strong>Total size:</strong> {formatBytes(totalSize)}
          </p>
          <p>
            <strong>State:</strong> {data.state} (terminal — no further transitions)
          </p>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">
          Exported Files ({data.files.length})
        </h4>
        <div className="space-y-2">
          {data.files.map((f) => (
            <div key={f.filename}>
              {FILE_DESCRIPTIONS[f.filename] && (
                <p className="text-xs text-gray-400 mb-1 ml-1">{FILE_DESCRIPTIONS[f.filename]}</p>
              )}
              <ExportFileRow file={f} />
            </div>
          ))}
        </div>
      </div>

      <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-sm text-gray-600">
        The session is now <strong>finalized</strong>. No download endpoint is available — use the
        file paths above to access exported files on the server.
      </div>
    </div>
  )
}

export default function ExportStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runExport(sessionId),
    onSuccess,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Export & Finalize</h2>
      <p className="text-sm text-gray-500 mb-2">
        Generate all output files and finalize the session. This advances the session to the
        terminal <strong>finalized</strong> state — no further transitions are possible.
      </p>
      <div className="bg-amber-50 border border-amber-100 rounded-md p-3 text-sm text-amber-800 mb-5">
        Generates: final_matches.csv, residual_unmatched_gl.csv, residual_unmatched_sub.csv,
        rejected_matches.csv, audit_log.csv, reconciliation_report.pdf
      </div>

      {mutation.error && (
        <div className="mb-4">
          <ErrorDisplay error={mutation.error} onRefresh={onSuccess} />
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {mutation.isPending ? 'Exporting…' : 'Export & Finalize'}
      </button>

      {mutation.data && <ExportResult data={mutation.data} />}
    </div>
  )
}
