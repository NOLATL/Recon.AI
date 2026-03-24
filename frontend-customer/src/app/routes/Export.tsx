import { useState, useEffect } from 'react'
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
  RECON_SESSION_ID_KEY,
  runExport,
  getExportManifest,
  getExportZipUrl,
} from '@/api/endpoints'

// White card styling (matches Matched Analysis page)
const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

// ── Artifact catalogue ────────────────────────────────────────────────────────

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

export function Export() {
  const sessionId = localStorage.getItem(RECON_SESSION_ID_KEY) ?? ''

  useEffect(() => { window.scrollTo(0, 0) }, [])

  const [selectedArtifacts, setSelectedArtifacts] = useState<Set<string>>(new Set())
  const [exportLoading, setExportLoading] = useState(false)
  const [exportError,   setExportError]   = useState<string | null>(null)

  const toggleArtifact = (id: string) => {
    setSelectedArtifacts(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectAll = () => {
    setSelectedArtifacts(new Set(EXPORT_ARTIFACTS.map(a => a.id)))
  }

  const selectAllData = () => {
    setSelectedArtifacts(prev => {
      const next = new Set(prev)
      EXPORT_ARTIFACTS.filter(a => a.group === 'data').forEach(a => next.add(a.id))
      return next
    })
  }

  const handleDownload = async () => {
    if (!sessionId) { setExportError('No session.'); return }
    if (selectedArtifacts.size === 0) { setExportError('Select at least one item to export.'); return }
    setExportLoading(true)
    setExportError(null)
    try {
      // Run export (idempotent — 409 means already finalized, which is fine).
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

      // Trigger a single ZIP download — avoids popup-blocker issues.
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

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <PageLayout title="Export" description="Download the reconciliation package.">
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Export Reconciliation Package</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            Choose which artifacts to include. Download produces a single ZIP file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Selection controls */}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={selectAll}
              className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">
              Select all
            </Button>
            <Button variant="outline" size="sm" onClick={selectAllData}
              className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">
              Select all data sets
            </Button>
            <Button variant="outline" size="sm" onClick={() => setSelectedArtifacts(new Set())}
              className="bg-white border-gray-200 text-[#1a1a1a] hover:bg-gray-50">
              Clear
            </Button>
          </div>

          {/* Artifact checklist */}
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-[#1a1a1a]">Data sets</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter(a => a.group === 'data').map(artifact => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label htmlFor={artifact.id} className="cursor-pointer text-sm text-[#1a1a1a]">
                      {artifact.label}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-[#1a1a1a]">Narrative</p>
              <ul className="space-y-2">
                {EXPORT_ARTIFACTS.filter(a => a.group === 'narrative').map(artifact => (
                  <li key={artifact.id} className="flex items-center gap-3">
                    <Checkbox
                      id={artifact.id}
                      checked={selectedArtifacts.has(artifact.id)}
                      onCheckedChange={() => toggleArtifact(artifact.id)}
                      aria-label={`Include ${artifact.label}`}
                    />
                    <label htmlFor={artifact.id} className="cursor-pointer text-sm text-[#1a1a1a]">
                      {artifact.label}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Download */}
          <div className="border-t border-gray-200 pt-4">
            <Button onClick={handleDownload} size="lg" variant="brand" disabled={exportLoading}>
              {exportLoading ? (
                <><Loader2 className="size-4 animate-spin" aria-hidden />Exporting…</>
              ) : (
                <><Download className="size-4" aria-hidden />Download Export Package</>
              )}
            </Button>
            {exportError && <p className="mt-2 text-sm text-destructive">{exportError}</p>}
            {selectedArtifacts.size > 0 && (
              <p className="mt-2 text-sm text-[#1a1a1a]/70">
                {selectedArtifacts.size} item(s) selected for export.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </PageLayout>
  )
}
