import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import { FileDropzone, type UploadStatus } from '@/components/upload/FileDropzone'
import { VendorPreprocessingTable } from '@/components/VendorPreprocessingTable'
import { ColumnHistogramHover } from '@/components/upload/ColumnHistogramHover'
import {
  RECON_SESSION_ID_KEY,
  startSession,
  uploadFiles,
  runProfile,
  getProfile,
  runPreprocess,
  getPreprocess,
  applyVendorOverrides,
  runDeterministic,
  metricsToFileProfile,
  ApiError,
  type FileProfile,
  type ProfilingResponse,
} from '@/api/endpoints'

type NormEntry = {
  original_vendor: string
  normalized_vendor: string
  matched_to: string | null
  match_source: string
}

// White card styling per mockup (used for upload cards and post-process cards)
const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

// One-sentence descriptions shown in column hover tooltips
const COLUMN_DESCRIPTIONS: Record<string, string> = {
  gl_id:            'Unique identifier for each General Ledger transaction record.',
  subledger_id:     'Unique identifier for each Subledger transaction record.',
  entity:           'Business or legal entity associated with the transaction.',
  account_code:     'General Ledger account code used to classify the transaction.',
  vendor_name:      'Name of the vendor or supplier involved in the transaction.',
  transaction_date: 'Date on which the transaction was recorded or posted.',
  amount:           'Transaction monetary amount in the specified currency.',
  currency:         'ISO 4217 currency code for the transaction amount.',
  exception_flag:   'Indicates whether this transaction has been flagged as an exception requiring review.',
  reference_id:     'Reference identifier linking this Subledger record to its General Ledger counterpart.',
  materiality_threshold: 'Dollar threshold above which a difference is considered material.',
}

function fmt(val: number | null | undefined, decimals = 0): string {
  if (val == null) return '—'
  return val.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function DataDescriptionSection({ label, profile }: { label: string; profile: FileProfile }) {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-foreground">{label}</h3>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Row Count</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-[#1a1a1a]">{profile.row_count.toLocaleString()}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Unique Vendors</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-[#1a1a1a]">{profile.unique_vendors}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Date Range</p>
          <p className="mt-1 text-lg font-bold tabular-nums text-[#1a1a1a]">
            {profile.date_from} – {profile.date_to}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Total Amount</p>
          <p className="mt-1 text-3xl font-bold tabular-nums text-[#1a1a1a]">
            ${profile.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </div>
      </div>
      {profile.column_stats.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-[#1a1a1a] uppercase tracking-wide">Data Description</p>
          <p className="mb-2 text-xs text-[#1a1a1a]">Hover a column name for description and distribution.</p>
          <div className="overflow-x-auto">
            <Table className="text-xs table-auto w-full">
              <TableHeader>
                <TableRow className="bg-[#1a1a1a]">
                  <TableHead className="whitespace-nowrap font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Column</TableHead>
                  <TableHead className="whitespace-nowrap font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Type</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Cnt Unique</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Cnt Null</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Null %</TableHead>
                  {/* Numeric stats: Min, Max, Sum, Avg, Std Dev, Median */}
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Min</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Max</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Sum</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Avg</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Std Dev</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Median</TableHead>
                  {/* String stats */}
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Max Len</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Min Len</TableHead>
                  <TableHead className="text-right font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Blanks</TableHead>
                  <TableHead className="font-bold text-white bg-[#1a1a1a] py-1.5 px-2">Mode</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {profile.column_stats.map((col) => (
                  <TableRow key={col.name}>
                    <TableCell className="whitespace-nowrap font-mono text-xs py-1 px-2">
                      <ColumnHistogramHover
                        columnName={col.name}
                        buckets={col.histogram ?? []}
                        description={COLUMN_DESCRIPTIONS[col.name]}
                      />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-[#1a1a1a] capitalize py-1 px-2">{col.data_type}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2">{col.unique_count.toLocaleString()}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2">{col.null_count.toLocaleString()}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2">{col.null_pct != null ? `${Math.round(col.null_pct)}%` : '—'}</TableCell>
                    {/* Numeric: Min, Max, Sum, Avg, Std Dev, Median */}
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.min as number) : col.data_type === 'date' ? String(col.min ?? '—') : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.max as number) : col.data_type === 'date' ? String(col.max ?? '—') : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.sum) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.mean) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.std) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'numeric' ? fmt(col.median) : '—'}</TableCell>
                    {/* String */}
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'string' ? (col.max_len ?? '—') : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'string' ? (col.min_len ?? '—') : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums text-xs py-1 px-2 text-[#1a1a1a]">{col.data_type === 'string' ? (col.blank_count ?? '—') : '—'}</TableCell>
                    <TableCell className="font-mono text-xs py-1 px-2 text-[#1a1a1a] max-w-[80px] truncate" title={col.mode ?? undefined}>{col.data_type === 'string' ? (col.mode ?? '—') : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  )
}

export function LoadFiles() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem(RECON_SESSION_ID_KEY)
  )
  const [glFile, setGlFile] = useState<File | null>(null)
  const [slFile, setSlFile] = useState<File | null>(null)
  const [glStatus, setGlStatus] = useState<UploadStatus>('idle')
  const [slStatus, setSlStatus] = useState<UploadStatus>('idle')
  const [vendorNormMap, setVendorNormMap] = useState<NormEntry[]>([])
  const [unmatchedSubVendors, setUnmatchedSubVendors] = useState<string[]>([])
  const [unmatchedSubNormalized, setUnmatchedSubNormalized] = useState<Record<string, string>>({})
  const [vendorOverrides, setVendorOverrides] = useState<Record<string, string>>({})
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [profileResponse, setProfileResponse] = useState<ProfilingResponse | null>(null)
  const [glProfile, setGlProfile] = useState<FileProfile | null>(null)
  const [slProfile, setSlProfile] = useState<FileProfile | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)

  const hasAllFiles = glFile != null && slFile != null

  // Ensure we have a session on mount
  useEffect(() => {
    let cancelled = false
    const existing = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (existing) {
      setSessionId(existing)
      return
    }
    startSession()
      .then((res) => {
        if (!cancelled && res.session_id) {
          localStorage.setItem(RECON_SESSION_ID_KEY, res.session_id)
          setSessionId(res.session_id)
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // Called by "Process Data" button — upload, profile, then preprocess
  const doUploadAndProfile = useCallback(async () => {
    if (!sessionId || !glFile || !slFile) return
    setProfileLoading(true)
    setProfileError(null)
    setGlStatus('uploading')
    setSlStatus('uploading')
    try {
      // Use a local session ID so we can swap it if the backend restarted (404).
      let sid = sessionId
      try {
        await uploadFiles(sid, glFile, slFile)
      } catch (uploadErr) {
        if (uploadErr instanceof ApiError && uploadErr.status === 409) {
          // Already uploaded — continue
        } else if (uploadErr instanceof ApiError && uploadErr.status === 404) {
          // Backend restarted — old session lost. Create a fresh one and retry.
          const newSession = await startSession()
          sid = newSession.session_id
          localStorage.setItem(RECON_SESSION_ID_KEY, sid)
          setSessionId(sid)
          await uploadFiles(sid, glFile, slFile)
        } else {
          throw uploadErr
        }
      }
      setGlStatus('done')
      setSlStatus('done')
      let profileRes: Awaited<ReturnType<typeof runProfile>>
      try {
        profileRes = await runProfile(sid)
      } catch (profileErr) {
        if (profileErr instanceof ApiError && profileErr.status === 409) {
          profileRes = await getProfile(sid)
        } else {
          throw profileErr
        }
      }
      setProfileResponse(profileRes)
      const metrics = profileRes.metrics
      const gl = metricsToFileProfile('gl', metrics)
      const sl = metricsToFileProfile('subledger', metrics)
      setGlProfile(gl ?? null)
      setSlProfile(sl ?? null)

      // Run preprocessing to get vendor normalization map
      let normMap: NormEntry[] = []
      let unmatchedSubs: string[] = []
      let unmatchedNorm: Record<string, string> = {}
      try {
        const preprocessRes = await runPreprocess(sid)
        normMap = (preprocessRes.vendor_normalization_map ?? []) as NormEntry[]
        unmatchedSubs = preprocessRes.unmatched_sub_vendors ?? []
        unmatchedNorm = preprocessRes.unmatched_sub_normalized ?? {}
      } catch (preprocessErr) {
        if (preprocessErr instanceof ApiError && preprocessErr.status === 409) {
          // Already preprocessed — fetch stored map via GET endpoint
          try {
            const stored = await getPreprocess(sid)
            normMap = (stored.vendor_normalization_map ?? []) as NormEntry[]
            unmatchedSubs = stored.unmatched_sub_vendors ?? []
            unmatchedNorm = stored.unmatched_sub_normalized ?? {}
          } catch { normMap = [] }
        }
        // Other errors: silently skip — vendor table shows empty, matching still works
      }
      setVendorNormMap(normMap)
      setUnmatchedSubVendors(unmatchedSubs)
      setUnmatchedSubNormalized(unmatchedNorm)
      // Pre-populate overrides for unmatched sub vendors only.
      // AI-matched GL vendors are intentionally excluded: the backend already aligns
      // both GL and Sub to the same Vendor_Normalized (sub's normalized form), so
      // sending an override here would break the equality join downstream.
      if (Object.keys(unmatchedNorm).length > 0) {
        setVendorOverrides((prev) => {
          const next = { ...prev }
          for (const [vendor, normalized] of Object.entries(unmatchedNorm)) {
            const key = `__sub__${vendor}`
            if (!(key in next)) next[key] = normalized
          }
          return next
        })
      }
    } catch (err) {
      let msg = err instanceof Error ? err.message : 'Upload or profile failed'
      if (err instanceof ApiError && err.body != null) {
        const detail = (err.body as { detail?: unknown }).detail
        if (Array.isArray(detail)) {
          const parts = detail.map((d: { file_key?: string; missing_columns?: string[]; column_errors?: Array<{ column: string; expected_dtype: string; sample_bad_values: string[] }> }) => {
            const file = d.file_key ?? 'file'
            if (d.missing_columns?.length) {
              return `${file}: Missing columns ${d.missing_columns.join(', ')}`
            }
            if (d.column_errors?.length) {
              return d.column_errors.map((e: { column: string; expected_dtype: string; sample_bad_values: string[] }) =>
                `${file} column '${e.column}' expects ${e.expected_dtype}; invalid samples: ${(e.sample_bad_values ?? []).slice(0, 3).join(', ')}`
              ).join(' | ')
            }
            return `${file}: validation failed`
          })
          msg = parts.length ? `${msg}\n${parts.join('\n')}` : msg
        } else if (typeof detail === 'string') {
          msg = `${msg}\n${detail}`
        }
      }
      const hint =
        msg.toLowerCase().includes('failed to fetch') || msg.toLowerCase().includes('network')
          ? ' — Is the backend running? Start it with: uvicorn src.api.main:app --reload --port 8000'
          : ''
      setProfileError(msg + hint)
      setGlStatus(glFile ? 'done' : 'idle')
      setSlStatus(slFile ? 'done' : 'idle')
    } finally {
      setProfileLoading(false)
    }
  }, [sessionId, glFile, slFile])

  // Reset profiling state when files are removed
  useEffect(() => {
    if (!hasAllFiles) {
      setProfileResponse(null)
      setGlProfile(null)
      setSlProfile(null)
      setProfileError(null)
      setVendorNormMap([])
      setUnmatchedSubVendors([])
      setUnmatchedSubNormalized({})
    }
  }, [hasAllFiles])

  const handleRunMatching = async () => {
    if (!sessionId || !profileResponse) return
    setRunError(null)
    setIsRunning(true)
    try {
      // Apply manual vendor overrides before matching so they are used for matching and output
      if (Object.keys(vendorOverrides).length > 0) {
        await applyVendorOverrides(sessionId, vendorOverrides)
      }
      try { await runDeterministic(sessionId) } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e
      }
      navigate('/matching')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Run matching failed'
      setRunError(message)
      console.error('Run matching failed:', err)
    } finally {
      setIsRunning(false)
    }
  }

  const handleGlChange = (file: File | null) => {
    setGlFile(file)
    setGlStatus(file ? 'done' : 'idle')
  }

  const handleSlChange = (file: File | null) => {
    setSlFile(file)
    setSlStatus(file ? 'done' : 'idle')
  }

  const handleVendorOverride = (key: string, value: string) => {
    setVendorOverrides((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <PageLayout title="Load & Clean Data" description="Upload your General Ledger and Subledger files, then click Process Data.">
      <section className="grid gap-6 md:grid-cols-2">
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <FileDropzone
              label="General Ledger"
              value={glFile}
              onChange={handleGlChange}
              status={glStatus}
            />
          </CardContent>
        </Card>
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <FileDropzone
              label="Subledger"
              value={slFile}
              onChange={handleSlChange}
              status={slStatus}
            />
          </CardContent>
        </Card>
      </section>

      {/* Process Data button — shown before profiling starts (red, like Get Started) */}
      {hasAllFiles && !profileResponse && !profileLoading && (
        <div className="mt-2">
          <Button size="lg" variant="default" onClick={doUploadAndProfile}>
            Process Data
          </Button>
        </div>
      )}

      {/* Data Profiling — shown while loading, after complete, or on error (so error is visible) */}
      {(profileLoading || profileResponse || profileError) && (
        <section>
          <Card className={whiteCardClass}>
            <CardHeader>
              <CardTitle className="text-[#1a1a1a]">Data Profiling</CardTitle>
              <CardDescription className="text-[#1a1a1a]">
                {profileLoading
                  ? 'Uploading and profiling files…'
                  : profileError
                    ? 'Profiling failed. Ensure backend is running and filenames are Chart_of_Accounts.csv, GL.csv, Subledger.csv.'
                    : 'Summary and columns per file. Hover column names for distribution.'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {profileError && (
                <p className="text-sm text-destructive whitespace-pre-line">{profileError}</p>
              )}
              {profileLoading && !profileResponse && (
                <div className="flex items-center gap-2 text-sm text-[#1a1a1a]">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Uploading and profiling…
                </div>
              )}
              {profileResponse && !glProfile && !slProfile && (
                <>
                  {profileResponse.narrative && (
                    <div className="rounded-lg border border-gray-200 bg-white p-4">
                      <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Summary</p>
                      <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{profileResponse.narrative}</p>
                    </div>
                  )}
                  {profileResponse.metrics?.cross_file && (
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                      <div className="rounded-lg border border-gray-200 bg-white p-4">
                        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">GL rows</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.gl_row_count?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-white p-4">
                        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Subledger rows</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.subledger_row_count?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-white p-4">
                        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Row delta</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-white p-4">
                        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Delta %</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta_pct != null ? `${profileResponse.metrics.cross_file.row_count_delta_pct}%` : '—'}</p>
                      </div>
                    </div>
                  )}
                  {profileResponse.metrics?.files && typeof profileResponse.metrics.files === 'object' && (
                    <div className="space-y-4">
                      {Object.entries(profileResponse.metrics.files).map(([key, file]) => {
                        const fr = file as unknown as Record<string, unknown>
                        const rowCount = typeof fr.row_count === 'number' ? fr.row_count : 0
                        const nullCounts = (fr.null_counts as Record<string, number>) ?? {}
                        return (
                          <div key={key} className="space-y-2">
                            <h3 className="text-lg font-semibold capitalize">{key.replace('_', ' ')}</h3>
                            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                              <div className="rounded-lg border border-gray-200 bg-white p-4">
                                <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Row count</p>
                                <p className="mt-1 text-2xl font-bold tabular-nums">{rowCount.toLocaleString()}</p>
                              </div>
                              <div className="rounded-lg border border-gray-200 bg-white p-4">
                                <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Duplicate rows</p>
                                <p className="mt-1 text-2xl font-bold tabular-nums">{(typeof fr.duplicate_row_count === 'number' ? fr.duplicate_row_count : 0).toLocaleString()}</p>
                              </div>
                            </div>
                            {Object.keys(nullCounts).length > 0 && (
                              <>
                                <p className="text-xs text-[#1a1a1a]">Null counts by column</p>
                                <Table>
                                  <TableHeader>
                                    <TableRow className="bg-[#1a1a1a]">
                                      <TableHead className="font-bold text-white bg-[#1a1a1a]">Column</TableHead>
                                      <TableHead className="font-bold text-white bg-[#1a1a1a]">Null count</TableHead>
                                      <TableHead className="font-bold text-white bg-[#1a1a1a]">Null %</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {Object.entries(nullCounts).map(([col, count]) => (
                                      <TableRow key={col}>
                                        <TableCell className="font-mono text-sm">{col}</TableCell>
                                        <TableCell className="tabular-nums">{count.toLocaleString()}</TableCell>
                                        <TableCell className="tabular-nums">
                                          {((rowCount > 0 ? (count / rowCount) * 100 : 0).toFixed(2))}%
                                        </TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </>
              )}
              {profileResponse?.narrative && (glProfile || slProfile) && (
                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Summary</p>
                  <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{profileResponse.narrative}</p>
                </div>
              )}
              {profileResponse?.metrics?.cross_file && (glProfile || slProfile) && (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">GL rows</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.gl_row_count?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Subledger rows</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.subledger_row_count?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Row delta</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Delta %</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta_pct != null ? `${profileResponse.metrics.cross_file.row_count_delta_pct}%` : '—'}</p>
                  </div>
                </div>
              )}
              {glProfile && (
                <DataDescriptionSection label="General Ledger" profile={glProfile} />
              )}
              {slProfile && (
                <DataDescriptionSection label="Subledger" profile={slProfile} />
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* Vendor Preprocessing — shown after processing runs (or while loading) */}
      {(profileLoading || profileResponse || profileError) && (
        <section>
          <Card className={whiteCardClass}>
            <CardHeader>
              <CardTitle className="text-[#1a1a1a]">Vendor Preprocessing</CardTitle>
              <CardDescription className="text-[#1a1a1a]">
                Vendor normalization map generated from your input files. GL vendor names are
                matched to subledger vendor names and standardized. Override the standardized
                name for any row below.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {vendorNormMap.length === 0 && profileLoading ? (
                <div className="flex items-center gap-2 text-sm text-[#1a1a1a] py-4">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Running vendor normalization…
                </div>
              ) : vendorNormMap.length === 0 ? (
                <p className="text-sm text-[#1a1a1a] py-4">
                  No vendor normalization data available.
                </p>
              ) : (
                <VendorPreprocessingTable
                  vendorNormMap={vendorNormMap}
                  unmatchedSubVendors={unmatchedSubVendors}
                  unmatchedSubNormalized={unmatchedSubNormalized}
                  vendorOverrides={vendorOverrides}
                  onVendorOverride={handleVendorOverride}
                />
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* Footer CTA — shown only after processing completes */}
      {profileResponse && (
        <footer className="flex flex-col items-start gap-4 border-t pt-6">
          <Button
            size="lg"
            disabled={isRunning}
            onClick={handleRunMatching}
          >
            {isRunning ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Starting…
              </>
            ) : (
              <>
                Run Matching
                <ArrowRight className="size-4" aria-hidden />
              </>
            )}
          </Button>
          {runError && (
            <p className="text-sm text-destructive" role="alert">
              {runError}
            </p>
          )}
        </footer>
      )}
    </PageLayout>
  )
}
