import { useState, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { runExport, getExportManifest, getExportFileDownloadUrl } from '@/api/endpoints'
import type { ExportResponse, ExportFile, ReconciliationState } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  state: ReconciliationState
  onSuccess: () => void
}

const CACHE_KEY = (id: string) => `export_result_${id}`

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

const FILE_DESCRIPTIONS: Record<string, string> = {
  'final_matches.csv': 'All accepted matches across all layers',
  'residual_unmatched_gl.csv': 'GL records with no match found',
  'residual_unmatched_sub.csv': 'Subledger records with no match found',
  'rejected_matches.csv': 'All human-rejected match candidates',
  'audit_log.csv': 'Complete audit trail of all decisions and transitions',
  'reconciliation_report.pdf': 'Executive summary and statistics',
}

function ExportFileRow({ file, sessionId }: { file: ExportFile; sessionId: string }) {
  const isPdf = file.filename.endsWith('.pdf')
  const downloadUrl = getExportFileDownloadUrl(sessionId, file.filename)

  return (
    <div className="bg-void-elevated border border-void-border rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">{file.filename}</span>
            <span
              className={[
                'text-xs px-1.5 py-0.5 rounded font-medium',
                isPdf ? 'bg-bdo-red/15 text-bdo-red-light' : 'bg-emerald-500/15 text-emerald-400',
              ].join(' ')}
            >
              {isPdf ? 'PDF' : 'CSV'}
            </span>
          </div>
          <div className="flex gap-4 mt-1.5 text-xs text-white/35">
            <span>{formatBytes(file.size_bytes)}</span>
            <span className="font-mono truncate max-w-[200px]" title={file.sha256}>
              SHA256: {file.sha256.slice(0, 16)}…
            </span>
          </div>
        </div>
        <a
          href={downloadUrl}
          download={file.filename}
          className="flex-shrink-0 btn-primary text-xs px-3 py-1.5 no-underline"
        >
          ↓ Download
        </a>
      </div>
    </div>
  )
}

function DownloadAllButton({
  files,
  sessionId,
}: {
  files: ExportFile[]
  sessionId: string
}) {
  const handleDownloadAll = () => {
    files.forEach((f, i) => {
      setTimeout(() => {
        const a = document.createElement('a')
        a.href = getExportFileDownloadUrl(sessionId, f.filename)
        a.download = f.filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      }, i * 300) // stagger to avoid browser blocking multiple downloads
    })
  }

  return (
    <button
      onClick={handleDownloadAll}
      className="text-sm bg-gray-800 hover:bg-gray-900 text-white px-4 py-2 rounded-md transition-colors"
    >
      ↓ Download All ({files.length} files)
    </button>
  )
}

function ExportResult({ data, sessionId }: { data: ExportResponse; sessionId: string }) {
  const totalSize = data.files.reduce((sum, f) => sum + f.size_bytes, 0)

  return (
    <div className="mt-6 space-y-4">
      {/* Summary banner */}
      <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4">
        <p className="text-sm font-medium text-emerald-300 mb-2">
          Export complete — session finalized
        </p>
        <div className="text-sm text-emerald-400 space-y-1">
          <p>
            <strong>Exported at:</strong> {new Date(data.exported_at).toLocaleString()}
          </p>
          <p>
            <strong>Total size:</strong> {formatBytes(totalSize)} across {data.files.length} files
          </p>
        </div>
      </div>

      {/* Download all */}
      <DownloadAllButton files={data.files} sessionId={sessionId} />

      {/* Per-file list */}
      <div>
        <h4 className="text-sm font-medium text-white/70 mb-3">
          Exported Files ({data.files.length})
        </h4>
        <div className="space-y-2">
          {data.files.map((f) => (
            <div key={f.filename}>
              {FILE_DESCRIPTIONS[f.filename] && (
                <p className="text-xs text-white/35 mb-1 ml-1">{FILE_DESCRIPTIONS[f.filename]}</p>
              )}
              <ExportFileRow file={f} sessionId={sessionId} />
            </div>
          ))}
        </div>
      </div>

      <div className="bg-void-elevated border border-void-border rounded-xl p-3 text-xs text-white/50">
        <strong>Export directory (server):</strong>{' '}
        <span className="font-mono">{data.export_dir}</span>
      </div>
    </div>
  )
}

export default function ExportStep({ sessionId, state, onSuccess }: Props) {
  const isFinalized = state === 'finalized'

  // Attempt to restore cached result from sessionStorage
  const [cached, setCached] = useState<ExportResponse | null>(() => {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY(sessionId))
      return raw ? (JSON.parse(raw) as ExportResponse) : null
    } catch {
      return null
    }
  })

  // When already finalized and no local cache, fetch the manifest from the backend
  const manifestQuery = useQuery({
    queryKey: ['export-manifest', sessionId],
    queryFn: () => getExportManifest(sessionId),
    enabled: isFinalized && !cached,
    retry: 1,
  })

  // Persist fetched manifest to sessionStorage and local state
  useEffect(() => {
    if (manifestQuery.data && !cached) {
      try {
        sessionStorage.setItem(CACHE_KEY(sessionId), JSON.stringify(manifestQuery.data))
      } catch {
        // sessionStorage quota exceeded — skip caching
      }
      setCached(manifestQuery.data)
    }
  }, [manifestQuery.data, cached, sessionId])

  const mutation = useMutation({
    mutationFn: () => runExport(sessionId),
    onSuccess: (data) => {
      try {
        sessionStorage.setItem(CACHE_KEY(sessionId), JSON.stringify(data))
      } catch {
        // sessionStorage quota exceeded — skip caching
      }
      setCached(data)
      onSuccess()
    },
  })

  const displayData = cached ?? mutation.data

  return (
    <div className="glass-card p-6">
      <h2 className="text-base font-semibold text-white mb-1">Export & Finalize</h2>
      <p className="text-sm text-white/50 mb-4">
        Generate all output files and finalize the session. This advances the session to the
        terminal <strong>finalized</strong> state — no further transitions are possible.
      </p>

      {/* Export button — only shown when not yet finalized */}
      {!isFinalized && !displayData && (
        <>
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 text-sm text-amber-300 mb-5">
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
            className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? 'Exporting…' : 'Export & Finalize'}
          </button>
        </>
      )}

      {/* Loading state when fetching manifest for already-finalized session */}
      {isFinalized && !displayData && (
        <div className="mt-2 text-sm text-white/50">
          {manifestQuery.isLoading && 'Loading export manifest…'}
          {manifestQuery.error && (
            <ErrorDisplay
              error={manifestQuery.error}
              onRefresh={() => manifestQuery.refetch()}
            />
          )}
        </div>
      )}

      {/* Results with download buttons */}
      {displayData && <ExportResult data={displayData} sessionId={sessionId} />}
    </div>
  )
}
