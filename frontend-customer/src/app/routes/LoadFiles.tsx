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
import {
  ColumnHistogramHover,
  type HistogramBucket,
} from '@/components/upload/ColumnHistogramHover'
import {
  RECON_SESSION_ID_KEY,
  startSession,
  uploadFiles,
  runProfile,
  getProfile,
  runPreprocess,
  getPreprocess,
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

function toHistogramBuckets(buckets?: { label: string; count: number }[]): HistogramBucket[] {
  return buckets ?? []
}

export function LoadFiles() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem(RECON_SESSION_ID_KEY)
  )
  const [coaFile, setCoaFile] = useState<File | null>(null)
  const [glFile, setGlFile] = useState<File | null>(null)
  const [slFile, setSlFile] = useState<File | null>(null)
  const [coaStatus, setCoaStatus] = useState<UploadStatus>('idle')
  const [glStatus, setGlStatus] = useState<UploadStatus>('idle')
  const [slStatus, setSlStatus] = useState<UploadStatus>('idle')
  const [vendorNormMap, setVendorNormMap] = useState<NormEntry[]>([])
  const [vendorOverrides, setVendorOverrides] = useState<Record<string, string>>({})
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [profileResponse, setProfileResponse] = useState<ProfilingResponse | null>(null)
  const [glProfile, setGlProfile] = useState<FileProfile | null>(null)
  const [slProfile, setSlProfile] = useState<FileProfile | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [profileError, setProfileError] = useState<string | null>(null)

  const hasAllFiles = coaFile != null && glFile != null && slFile != null

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

  // When all three files are selected, upload then profile
  const doUploadAndProfile = useCallback(async () => {
    if (!sessionId || !coaFile || !glFile || !slFile) return
    setProfileLoading(true)
    setProfileError(null)
    setCoaStatus('uploading')
    setGlStatus('uploading')
    setSlStatus('uploading')
    try {
      // Use a local session ID so we can swap it if the backend restarted (404).
      let sid = sessionId
      try {
        await uploadFiles(sid, coaFile, glFile, slFile)
      } catch (uploadErr) {
        if (uploadErr instanceof ApiError && uploadErr.status === 409) {
          // Already uploaded — continue
        } else if (uploadErr instanceof ApiError && uploadErr.status === 404) {
          // Backend restarted — old session lost. Create a fresh one and retry.
          const newSession = await startSession()
          sid = newSession.session_id
          localStorage.setItem(RECON_SESSION_ID_KEY, sid)
          setSessionId(sid)
          await uploadFiles(sid, coaFile, glFile, slFile)
        } else {
          throw uploadErr
        }
      }
      setCoaStatus('done')
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
      try {
        const preprocessRes = await runPreprocess(sid)
        normMap = (preprocessRes.vendor_normalization_map ?? []) as NormEntry[]
      } catch (preprocessErr) {
        if (preprocessErr instanceof ApiError && preprocessErr.status === 409) {
          // Already preprocessed — fetch stored map via GET endpoint
          try {
            const stored = await getPreprocess(sid)
            normMap = (stored.vendor_normalization_map ?? []) as NormEntry[]
          } catch { normMap = [] }
        }
        // Other errors: silently skip — vendor table shows empty, matching still works
      }
      setVendorNormMap(normMap)
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Upload or profile failed'
      setProfileError(message)
      setCoaStatus(coaFile ? 'done' : 'idle')
      setGlStatus(glFile ? 'done' : 'idle')
      setSlStatus(slFile ? 'done' : 'idle')
    } finally {
      setProfileLoading(false)
    }
  }, [sessionId, coaFile, glFile, slFile])

  useEffect(() => {
    if (!hasAllFiles || !sessionId) {
      setProfileResponse(null)
      setGlProfile(null)
      setSlProfile(null)
      setProfileError(null)
      setVendorNormMap([])
      return
    }
    doUploadAndProfile()
  }, [hasAllFiles, sessionId, doUploadAndProfile])

  const handleRunMatching = async () => {
    if (!sessionId || !hasAllFiles) return
    setRunError(null)
    setIsRunning(true)
    try {
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

  const handleCoaChange = (file: File | null) => {
    setCoaFile(file)
    setCoaStatus(file ? 'done' : 'idle')
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
    <PageLayout title="Load Files" description="Upload Chart of Accounts, GL, and subledger files for reconciliation.">
      <section className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Chart of Accounts</CardTitle>
            <CardDescription>Upload Chart_of_Accounts.csv.</CardDescription>
          </CardHeader>
          <CardContent>
            <FileDropzone
              label="Chart of Accounts"
              value={coaFile}
              onChange={handleCoaChange}
              status={coaStatus}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>General Ledger Upload</CardTitle>
            <CardDescription>Upload GL.csv for reconciliation.</CardDescription>
          </CardHeader>
          <CardContent>
            <FileDropzone
              label="General Ledger"
              value={glFile}
              onChange={handleGlChange}
              status={glStatus}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Subledger Upload</CardTitle>
            <CardDescription>Upload Subledger.csv for reconciliation.</CardDescription>
          </CardHeader>
          <CardContent>
            <FileDropzone
              label="Subledger"
              value={slFile}
              onChange={handleSlChange}
              status={slStatus}
            />
          </CardContent>
        </Card>
      </section>

      {/* Data Profiling — runs after all three files are uploaded */}
      {hasAllFiles && (
        <section>
          <Card>
            <CardHeader>
              <CardTitle>Data Profiling</CardTitle>
              <CardDescription>
                {profileLoading
                  ? 'Uploading and profiling files…'
                  : profileError
                    ? 'Profiling failed. Ensure backend is running and filenames are Chart_of_Accounts.csv, GL.csv, Subledger.csv.'
                    : 'Summary and columns per file. Hover column names for distribution.'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {profileError && (
                <p className="text-sm text-destructive">{profileError}</p>
              )}
              {profileLoading && !profileResponse && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Uploading and profiling…
                </div>
              )}
              {profileResponse && !glProfile && !slProfile && (
                <>
                  {profileResponse.narrative && (
                    <div className="rounded-lg border bg-muted/30 p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Summary</p>
                      <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{profileResponse.narrative}</p>
                    </div>
                  )}
                  {profileResponse.metrics?.cross_file && (
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                      <div className="rounded-lg border bg-muted/30 p-4">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">GL rows</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.gl_row_count?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border bg-muted/30 p-4">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">Subledger rows</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.subledger_row_count?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border bg-muted/30 p-4">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">Row delta</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta?.toLocaleString() ?? '—'}</p>
                      </div>
                      <div className="rounded-lg border bg-muted/30 p-4">
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">Delta %</p>
                        <p className="mt-1 text-2xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta_pct != null ? `${profileResponse.metrics.cross_file.row_count_delta_pct}%` : '—'}</p>
                      </div>
                    </div>
                  )}
                  {profileResponse.metrics?.files && typeof profileResponse.metrics.files === 'object' && (
                    <div className="space-y-4">
                      {Object.entries(profileResponse.metrics.files).map(([key, file]) => {
                        const fr = file as Record<string, unknown>
                        const rowCount = typeof fr.row_count === 'number' ? fr.row_count : 0
                        const nullCounts = (fr.null_counts as Record<string, number>) ?? {}
                        return (
                          <div key={key} className="space-y-2">
                            <h3 className="text-lg font-semibold capitalize">{key.replace('_', ' ')}</h3>
                            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                              <div className="rounded-lg border bg-muted/30 p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Row count</p>
                                <p className="mt-1 text-2xl font-bold tabular-nums">{rowCount.toLocaleString()}</p>
                              </div>
                              <div className="rounded-lg border bg-muted/30 p-4">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground">Duplicate rows</p>
                                <p className="mt-1 text-2xl font-bold tabular-nums">{(typeof fr.duplicate_row_count === 'number' ? fr.duplicate_row_count : 0).toLocaleString()}</p>
                              </div>
                            </div>
                            {Object.keys(nullCounts).length > 0 && (
                              <>
                                <p className="text-xs text-muted-foreground">Null counts by column</p>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead>Column</TableHead>
                                      <TableHead>Null count</TableHead>
                                      <TableHead>Null %</TableHead>
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
                <div className="rounded-lg border bg-muted/30 p-4">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Summary</p>
                  <p className="mt-2 text-sm leading-relaxed whitespace-pre-line">{profileResponse.narrative}</p>
                </div>
              )}
              {profileResponse?.metrics?.cross_file && (glProfile || slProfile) && (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border bg-muted/30 p-4">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">GL rows</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.gl_row_count?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border bg-muted/30 p-4">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Subledger rows</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.subledger_row_count?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border bg-muted/30 p-4">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Row delta</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta?.toLocaleString() ?? '—'}</p>
                  </div>
                  <div className="rounded-lg border bg-muted/30 p-4">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Delta %</p>
                    <p className="mt-1 text-xl font-bold tabular-nums">{profileResponse.metrics.cross_file.row_count_delta_pct != null ? `${profileResponse.metrics.cross_file.row_count_delta_pct}%` : '—'}</p>
                  </div>
                </div>
              )}
              {glProfile && (
                <div className="space-y-4">
                  <h3 className="text-lg font-semibold text-foreground">General Ledger</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Row Count</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">{glProfile.row_count.toLocaleString()}</p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Unique Vendors</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">{glProfile.unique_vendors}</p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Date Range</p>
                      <p className="mt-1 text-lg font-bold tabular-nums text-foreground">
                        {glProfile.date_from} – {glProfile.date_to}
                      </p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Amount</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">
                        ${glProfile.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </p>
                    </div>
                  </div>
                    <div>
                    <p className="mb-2 text-xs text-muted-foreground">Hover a column name to see distribution.</p>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Column</TableHead>
                          <TableHead>Type</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {glProfile.columns.map((col) => (
                          <TableRow key={col.name}>
                            <TableCell>
                              <ColumnHistogramHover
                                columnName={col.name}
                                buckets={toHistogramBuckets(col.buckets)}
                              />
                            </TableCell>
                            <TableCell className="text-muted-foreground">{col.type}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  {profileResponse?.metrics?.files?.gl && typeof (profileResponse.metrics.files.gl as Record<string, unknown>).null_counts === 'object' && (
                    <div>
                      <p className="mb-2 text-xs text-muted-foreground">Null counts by column</p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Column</TableHead>
                            <TableHead>Null count</TableHead>
                            <TableHead>Null %</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {Object.entries((profileResponse.metrics.files.gl as Record<string, Record<string, number>>).null_counts ?? {}).map(([col, count]) => (
                            <TableRow key={col}>
                              <TableCell className="font-mono text-sm">{col}</TableCell>
                              <TableCell className="tabular-nums">{count.toLocaleString()}</TableCell>
                              <TableCell className="tabular-nums">
                                {glProfile.row_count > 0 ? ((count / glProfile.row_count) * 100).toFixed(2) : '0'}%
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </div>
              )}
              {slProfile && (
                <div className="space-y-4">
                  <h3 className="text-lg font-semibold text-foreground">Subledger</h3>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Row Count</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">{slProfile.row_count.toLocaleString()}</p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Unique Vendors</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">{slProfile.unique_vendors}</p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Date Range</p>
                      <p className="mt-1 text-lg font-bold tabular-nums text-foreground">
                        {slProfile.date_from} – {slProfile.date_to}
                      </p>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-6">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Total Amount</p>
                      <p className="mt-1 text-3xl font-bold tabular-nums text-foreground">
                        ${slProfile.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </p>
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-xs text-muted-foreground">Hover a column name to see distribution.</p>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Column</TableHead>
                          <TableHead>Type</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {slProfile.columns.map((col) => (
                          <TableRow key={col.name}>
                            <TableCell>
                              <ColumnHistogramHover
                                columnName={col.name}
                                buckets={toHistogramBuckets(col.buckets)}
                              />
                            </TableCell>
                            <TableCell className="text-muted-foreground">{col.type}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  {profileResponse?.metrics?.files?.subledger && typeof (profileResponse.metrics.files.subledger as Record<string, unknown>).null_counts === 'object' && (
                    <div>
                      <p className="mb-2 text-xs text-muted-foreground">Null counts by column</p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Column</TableHead>
                            <TableHead>Null count</TableHead>
                            <TableHead>Null %</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {Object.entries((profileResponse.metrics.files.subledger as Record<string, Record<string, number>>).null_counts ?? {}).map(([col, count]) => (
                            <TableRow key={col}>
                              <TableCell className="font-mono text-sm">{col}</TableCell>
                              <TableCell className="tabular-nums">{count.toLocaleString()}</TableCell>
                              <TableCell className="tabular-nums">
                                {slProfile.row_count > 0 ? ((count / slProfile.row_count) * 100).toFixed(2) : '0'}%
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* Vendor Preprocessing — populated after preprocessing runs */}
      {hasAllFiles && (
        <section>
          <Card>
            <CardHeader>
              <CardTitle>Vendor Preprocessing</CardTitle>
              <CardDescription>
                Vendor normalization map generated from your input files. GL vendor names are
                matched to subledger vendor names and standardized. Override the standardized
                name for any row below.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {vendorNormMap.length === 0 && profileLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Running vendor normalization…
                </div>
              ) : vendorNormMap.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4">
                  No vendor normalization data available.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>GL Vendor (Input)</TableHead>
                        <TableHead>Subledger Vendor (Input)</TableHead>
                        <TableHead>Standardized Vendor Name</TableHead>
                        <TableHead>Method</TableHead>
                        <TableHead className="w-[220px]">Override</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {vendorNormMap.map((entry) => {
                        const key = entry.original_vendor
                        const effective = vendorOverrides[key] || entry.normalized_vendor
                        return (
                          <TableRow key={key}>
                            <TableCell className="font-mono text-sm text-muted-foreground">
                              {entry.original_vendor}
                            </TableCell>
                            <TableCell className="font-mono text-sm text-muted-foreground">
                              {entry.matched_to ?? '—'}
                            </TableCell>
                            <TableCell className="font-mono text-sm font-medium">
                              {effective}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground capitalize">
                              {entry.match_source}
                            </TableCell>
                            <TableCell>
                              <Input
                                placeholder={entry.normalized_vendor}
                                value={vendorOverrides[key] ?? ''}
                                onChange={(e) => handleVendorOverride(key, e.target.value)}
                                className="h-8 text-sm"
                              />
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      {/* Footer CTA */}
      <footer className="flex flex-col items-start gap-4 border-t pt-6">
        <Button
          size="lg"
          disabled={!hasAllFiles || isRunning}
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
        {!hasAllFiles && (
          <p className="text-sm text-muted-foreground">
            Upload Chart of Accounts, General Ledger, and Subledger files to continue.
          </p>
        )}
      </footer>
    </PageLayout>
  )
}
