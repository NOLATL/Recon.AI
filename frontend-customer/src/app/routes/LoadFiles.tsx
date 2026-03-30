import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
  Legend,
} from 'recharts'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { FileDropzone, type UploadStatus } from '@/components/upload/FileDropzone'
import { VendorPreprocessingTable, computeFinalVendorName } from '@/components/VendorPreprocessingTable'
import { ColumnMappingSection } from '@/components/ColumnMappingSection'
import { MatchingConfigSection } from '@/components/MatchingConfigSection'
import { ChatPanel } from '@/components/ChatPanel'
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
  analyzeColumns,
  confirmColumnMapping,
  suggestMatchingConfig,
  confirmMatchingConfig,
  metricsToFileProfile,
  ApiError,
  type FileProfile,
  type ProfilingResponse,
  type AnalyzeColumnsResponse,
  type SideColumnMap,
  type SuggestMatchingConfigResponse,
  type DeterministicScenarioConfig,
  type ProbabilisticConfig,
  type MatchingConfigUpdate,
} from '@/api/endpoints'

type NormEntry = {
  original_vendor: string
  normalized_vendor: string
  matched_to: string | null
  match_source: string
  vendor_normalized_key: string
}

type Stage =
  | 'upload'
  | 'column_mapping'
  | 'vendor_cleanup'
  | 'eda'
  | 'reconciliation_design'
  | 'ready'

const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

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

// ─── Big-number KPI cards ────────────────────────────────────────────────────
function BanCards({ profile }: { profile: FileProfile }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Row Count</p>
        <p className="mt-1 text-3xl font-bold tabular-nums text-[#1a1a1a]">{profile.row_count.toLocaleString()}</p>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <p className="text-xs uppercase tracking-wide text-[#1a1a1a]">Unique Vendors</p>
        <p className="mt-1 text-3xl font-bold tabular-nums text-[#1a1a1a]">{profile.unique_vendors.toLocaleString()}</p>
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
  )
}

// ─── EDA Charts ──────────────────────────────────────────────────────────────
function VendorBarChart({
  title,
  data,
  dataKey,
  color,
  formatter,
  xMax,
}: {
  title: string
  data: { vendor: string; value: number }[]
  dataKey: string
  color: string
  formatter: (v: number) => string
  xMax?: number
}) {
  if (data.length === 0) return null
  const chartHeight = Math.max(220, data.length * 32)
  return (
    <div>
      <p className="text-sm font-semibold text-[#1a1a1a] mb-3">{title}</p>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
        >
          <XAxis
            type="number"
            domain={xMax != null ? [0, xMax] : [0, 'auto']}
            tick={{ fontSize: 11, fill: '#555' }}
            tickFormatter={formatter}
          />
          <YAxis
            dataKey="vendor"
            type="category"
            tick={{ fontSize: 11, fill: '#333' }}
            width={150}
          />
          <Tooltip
            formatter={(val: number | undefined) => [val != null ? formatter(val) : '', dataKey === 'value' ? title : '']}
            contentStyle={{ fontSize: 12 }}
          />
          <Bar dataKey="value" fill={color} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function AmountByDayChart({
  glData,
  slData,
}: {
  glData: { date: string; amount: number }[]
  slData: { date: string; amount: number }[]
}) {
  // Merge GL and SL data by date
  const merged = useMemo(() => {
    const allDates = new Set([...glData.map((d) => d.date), ...slData.map((d) => d.date)])
    const glMap = Object.fromEntries(glData.map((d) => [d.date, d.amount]))
    const slMap = Object.fromEntries(slData.map((d) => [d.date, d.amount]))
    return Array.from(allDates).sort().map((date) => ({
      date,
      GL: glMap[date] ?? 0,
      Subledger: slMap[date] ?? 0,
    }))
  }, [glData, slData])

  if (merged.length === 0) return null

  const fmtAmt = (v: number) =>
    `$${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}`

  // Thin out x-axis labels if many dates
  const tickInterval = merged.length > 60 ? Math.floor(merged.length / 20) : merged.length > 30 ? 3 : 0

  return (
    <div>
      <p className="text-sm font-semibold text-[#1a1a1a] mb-3">Amount by Day</p>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={merged} margin={{ top: 8, right: 24, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="date"
            height={80}
            interval={tickInterval}
            tick={({ x, y, payload }) => (
              <g transform={`translate(${x},${y})`}>
                <text
                  x={0}
                  y={0}
                  dy={14}
                  textAnchor="end"
                  fill="#555"
                  fontSize={10}
                  transform="rotate(-40)"
                >
                  {payload.value}
                </text>
              </g>
            )}
          />
          <YAxis tick={{ fontSize: 11, fill: '#555' }} tickFormatter={fmtAmt} width={56} />
          <Tooltip
            formatter={(val: number | undefined) => [`$${(val ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`, '']}
            contentStyle={{ fontSize: 12 }}
          />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          <Line
            type="monotone"
            dataKey="GL"
            stroke="#E81A3B"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
          <Line
            type="monotone"
            dataKey="Subledger"
            stroke="#0062B8"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export function LoadFiles() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem(RECON_SESSION_ID_KEY)
  )

  const [stage, setStage] = useState<Stage>('upload')

  // Scroll-target refs
  const columnMappingRef    = useRef<HTMLDivElement>(null)
  const vendorCleanupRef    = useRef<HTMLDivElement>(null)
  const edaRef              = useRef<HTMLDivElement>(null)
  const reconDesignRef      = useRef<HTMLDivElement>(null)
  const readyRef            = useRef<HTMLDivElement>(null)

  const scrollTo = (ref: React.RefObject<HTMLDivElement | null>) => {
    setTimeout(() => {
      requestAnimationFrame(() => {
        ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }, 400)
  }

  // Scroll to the correct section whenever stage changes (runs after DOM updates)
  useEffect(() => {
    const refMap: Partial<Record<Stage, React.RefObject<HTMLDivElement | null>>> = {
      column_mapping:       columnMappingRef,
      vendor_cleanup:       vendorCleanupRef,
      eda:                  edaRef,
      reconciliation_design: reconDesignRef,
      ready:                 readyRef,
    }
    const ref = refMap[stage]
    if (ref) scrollTo(ref)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage])

  // Upload
  const [glFile, setGlFile] = useState<File | null>(null)
  const [slFile, setSlFile] = useState<File | null>(null)
  const [glStatus, setGlStatus] = useState<UploadStatus>('idle')
  const [slStatus, setSlStatus] = useState<UploadStatus>('idle')
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // Column mapping
  const [columnAnalysis, setColumnAnalysis] = useState<AnalyzeColumnsResponse | null>(null)
  const [columnAnalysisLoading, setColumnAnalysisLoading] = useState(false)
  const [sideAMap, setSideAMap] = useState<SideColumnMap>({})
  const [sideBMap, setSideBMap] = useState<SideColumnMap>({})
  // true while auto-confirm + profile + preprocess runs in background after upload
  const [columnMappingLoading, setColumnMappingLoading] = useState(false)
  const [columnMappingError, setColumnMappingError] = useState<string | null>(null)

  // Profiling & preprocessing
  const [profileResponse, setProfileResponse] = useState<ProfilingResponse | null>(null)
  const [glProfile, setGlProfile] = useState<FileProfile | null>(null)
  const [slProfile, setSlProfile] = useState<FileProfile | null>(null)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [vendorNormMap, setVendorNormMap] = useState<NormEntry[]>([])
  const [unmatchedSubVendors, setUnmatchedSubVendors] = useState<string[]>([])
  const [unmatchedSubNormalized, setUnmatchedSubNormalized] = useState<Record<string, string>>({})
  const [glNormVendorRowDist, setGlNormVendorRowDist] = useState<Record<string, number>>({})
  const [glNormVendorAmtDist, setGlNormVendorAmtDist] = useState<Record<string, number>>({})
  const [slNormVendorRowDist, setSlNormVendorRowDist] = useState<Record<string, number>>({})
  const [slNormVendorAmtDist, setSlNormVendorAmtDist] = useState<Record<string, number>>({})
  const [vendorOverrides, setVendorOverrides] = useState<Record<string, string>>({})

  // Matching config
  const [matchingSuggestion, setMatchingSuggestion] = useState<SuggestMatchingConfigResponse | null>(null)
  const [matchingConfigLoading, setMatchingConfigLoading] = useState(false)
  const [detScenarios, setDetScenarios] = useState<DeterministicScenarioConfig[]>([])
  const [probConfig, setProbConfig] = useState<ProbabilisticConfig>({
    weights: {},
    threshold: 0.75,
    date_tolerance_days: 30,
    amount_pct_tolerance: 0.10,
    amount_abs_tolerance: 5.00,
  })
  const [matchingConfirming, setMatchingConfirming] = useState(false)
  const [matchingConfirmError, setMatchingConfirmError] = useState<string | null>(null)

  // Run matching
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  const hasAllFiles = glFile != null && slFile != null

  // ── Build display label map: Vendor_Normalized key → human-readable name ────
  // Priority: current override > normalized_vendor (the human-readable standardized name)
  // Key is vendor_normalized_key — the actual Vendor_Normalized written to the DataFrame,
  // which matches the distribution dict keys returned by the backend.
  const vendorDisplayMap = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const entry of vendorNormMap) {
      const key = entry.vendor_normalized_key || entry.normalized_vendor
      const override = vendorOverrides[entry.original_vendor]
      const finalName = computeFinalVendorName(entry, override)
      if (override?.trim()) {
        map[key] = finalName
      } else {
        if (!map[key]) map[key] = finalName
      }
    }
    // Unmatched sub vendors: unmatchedSubNormalized = { sub_vendor_name: normalized_form }
    for (const [subVendor, normalizedForm] of Object.entries(unmatchedSubNormalized)) {
      if (!map[normalizedForm]) {
        const override = vendorOverrides[`__sub__${subVendor}`]
        map[normalizedForm] = override?.trim() || subVendor
      }
    }
    return map
  }, [vendorNormMap, vendorOverrides, unmatchedSubNormalized])

  // ── Chart data derived from normalized vendor distributions ──────────────────
  // Relabel by display name then aggregate — multiple normalized keys can share
  // the same override name and must be summed into a single bar.
  function aggregateByDisplayName(
    dist: Record<string, number>,
    displayMap: Record<string, string>,
    top = 15,
  ): { vendor: string; value: number }[] {
    const acc = new Map<string, number>()
    for (const [normKey, value] of Object.entries(dist)) {
      const label = displayMap[normKey] ?? normKey
      acc.set(label, (acc.get(label) ?? 0) + value)
    }
    return Array.from(acc.entries())
      .map(([vendor, value]) => ({ vendor, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, top)
  }

  const glVendorRowData = useMemo(() =>
    Object.keys(glNormVendorRowDist).length > 0
      ? aggregateByDisplayName(glNormVendorRowDist, vendorDisplayMap)
      : Object.entries(glProfile?.vendor_row_distribution ?? {})
          .map(([vendor, value]) => ({ vendor, value }))
          .sort((a, b) => b.value - a.value),
    [glNormVendorRowDist, glProfile, vendorDisplayMap]
  )
  const slVendorRowData = useMemo(() =>
    Object.keys(slNormVendorRowDist).length > 0
      ? aggregateByDisplayName(slNormVendorRowDist, vendorDisplayMap)
      : Object.entries(slProfile?.vendor_row_distribution ?? {})
          .map(([vendor, value]) => ({ vendor, value }))
          .sort((a, b) => b.value - a.value),
    [slNormVendorRowDist, slProfile, vendorDisplayMap]
  )
  const glVendorAmtData = useMemo(() =>
    Object.keys(glNormVendorAmtDist).length > 0
      ? aggregateByDisplayName(glNormVendorAmtDist, vendorDisplayMap)
      : Object.entries(glProfile?.vendor_amount_distribution ?? {})
          .map(([vendor, value]) => ({ vendor, value }))
          .sort((a, b) => b.value - a.value),
    [glNormVendorAmtDist, glProfile, vendorDisplayMap]
  )
  const slVendorAmtData = useMemo(() =>
    Object.keys(slNormVendorAmtDist).length > 0
      ? aggregateByDisplayName(slNormVendorAmtDist, vendorDisplayMap)
      : Object.entries(slProfile?.vendor_amount_distribution ?? {})
          .map(([vendor, value]) => ({ vendor, value }))
          .sort((a, b) => b.value - a.value),
    [slNormVendorAmtDist, slProfile, vendorDisplayMap]
  )
  const glDailyData = useMemo(() =>
    Object.entries(glProfile?.daily_amount_distribution ?? {})
      .map(([date, amount]) => ({ date, amount }))
      .sort((a, b) => a.date.localeCompare(b.date)),
    [glProfile]
  )
  const slDailyData = useMemo(() =>
    Object.entries(slProfile?.daily_amount_distribution ?? {})
      .map(([date, amount]) => ({ date, amount }))
      .sort((a, b) => a.date.localeCompare(b.date)),
    [slProfile]
  )

  // Ensure session on mount
  useEffect(() => {
    let cancelled = false
    const existing = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (existing) { setSessionId(existing); return }
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

  // Reset when files removed
  useEffect(() => {
    if (!hasAllFiles) {
      setStage('upload')
      setProfileResponse(null)
      setGlProfile(null)
      setSlProfile(null)
      setProfileError(null)
      setVendorNormMap([])
      setUnmatchedSubVendors([])
      setUnmatchedSubNormalized({})
      setColumnAnalysis(null)
      setColumnMappingLoading(false)
      setColumnMappingError(null)
      setMatchingSuggestion(null)
      setSideAMap({})
      setSideBMap({})
    }
  }, [hasAllFiles])

  // ── Stage 1: Upload → analyze columns → auto-confirm → profile → preprocess ──
  const handleProcessData = useCallback(async () => {
    if (!sessionId || !glFile || !slFile) return
    setUploadLoading(true)
    setUploadError(null)
    setGlStatus('uploading')
    setSlStatus('uploading')

    let sid = sessionId
    try {
      // 1a. Upload
      try {
        await uploadFiles(sid, glFile, slFile)
      } catch (uploadErr) {
        if (uploadErr instanceof ApiError && uploadErr.status === 409) {
          // already uploaded — continue
        } else if (uploadErr instanceof ApiError && uploadErr.status === 404) {
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
      setUploadLoading(false)

      // 1b. Analyze columns
      setColumnAnalysisLoading(true)
      let analysis: AnalyzeColumnsResponse
      try {
        analysis = await analyzeColumns(sid)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          analysis = {
            side_a_label: 'GL',
            side_b_label: 'Subledger',
            side_a_suggestions: [],
            side_b_suggestions: [],
            analysis_narrative: '',
          }
        } else {
          throw e
        }
      }
      const buildMap = (suggestions: AnalyzeColumnsResponse['side_a_suggestions']): SideColumnMap => {
        const m: SideColumnMap = {}
        for (const s of suggestions) {
          if (s.detected_role && s.detected_role !== 'ignore' && !m[s.detected_role]) {
            m[s.detected_role] = s.column_name
          }
        }
        return m
      }
      const aiSideAMap = buildMap(analysis.side_a_suggestions)
      const aiSideBMap = buildMap(analysis.side_b_suggestions)
      setColumnAnalysis(analysis)
      setSideAMap(aiSideAMap)
      setSideBMap(aiSideBMap)
      setColumnAnalysisLoading(false)

      // Show column mapping section immediately — stats arrive below
      setStage('column_mapping')
      setColumnMappingLoading(true)
      setColumnMappingError(null)
      setProfileError(null)

      // 1c. Auto-confirm column mapping with AI defaults
      try {
        await confirmColumnMapping(sid, {
          column_map: {
            side_a_label: analysis.side_a_label,
            side_b_label: analysis.side_b_label,
            side_a: aiSideAMap,
            side_b: aiSideBMap,
          },
        })
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e
      }

      // 1d. Profile
      let profileRes: Awaited<ReturnType<typeof runProfile>>
      try {
        profileRes = await runProfile(sid)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          profileRes = await getProfile(sid)
        } else {
          throw e
        }
      }
      setProfileResponse(profileRes)
      setGlProfile(metricsToFileProfile('gl', profileRes.metrics))
      setSlProfile(metricsToFileProfile('subledger', profileRes.metrics))

      setColumnMappingLoading(false)

    } catch (err) {
      setGlStatus(glFile ? 'done' : 'idle')
      setSlStatus(slFile ? 'done' : 'idle')
      const msg = err instanceof Error ? err.message : 'Processing failed'
      if (stage === 'column_mapping') {
        setColumnMappingError(msg)
        setColumnMappingLoading(false)
      } else {
        setUploadError(msg)
        setStage('upload')
      }
    } finally {
      setUploadLoading(false)
      setColumnAnalysisLoading(false)
    }
  }, [sessionId, glFile, slFile, stage])

  // ── Stage 2: User confirms column mapping → run preprocess → show vendor cleanup ──
  const handleConfirmColumns = useCallback(async () => {
    if (!sessionId) return
    setColumnMappingLoading(true)
    setColumnMappingError(null)
    try {
      let normMap: NormEntry[] = []
      let unmatchedSubs: string[] = []
      let unmatchedNorm: Record<string, string> = {}
      try {
        const preprocessRes = await runPreprocess(sessionId)
        normMap       = (preprocessRes.vendor_normalization_map ?? []) as NormEntry[]
        unmatchedSubs = preprocessRes.unmatched_sub_vendors ?? []
        unmatchedNorm = preprocessRes.unmatched_sub_normalized ?? {}
        setGlNormVendorRowDist(preprocessRes.gl_normalized_vendor_row_distribution ?? {})
        setGlNormVendorAmtDist(preprocessRes.gl_normalized_vendor_amt_distribution ?? {})
        setSlNormVendorRowDist(preprocessRes.sl_normalized_vendor_row_distribution ?? {})
        setSlNormVendorAmtDist(preprocessRes.sl_normalized_vendor_amt_distribution ?? {})
      } catch (preprocessErr) {
        if (preprocessErr instanceof ApiError && preprocessErr.status === 409) {
          try {
            const stored = await getPreprocess(sessionId)
            normMap       = (stored.vendor_normalization_map ?? []) as NormEntry[]
            unmatchedSubs = stored.unmatched_sub_vendors ?? []
            unmatchedNorm = stored.unmatched_sub_normalized ?? {}
            setGlNormVendorRowDist(stored.gl_normalized_vendor_row_distribution ?? {})
            setGlNormVendorAmtDist(stored.gl_normalized_vendor_amt_distribution ?? {})
            setSlNormVendorRowDist(stored.sl_normalized_vendor_row_distribution ?? {})
            setSlNormVendorAmtDist(stored.sl_normalized_vendor_amt_distribution ?? {})
          } catch { normMap = [] }
        } else {
          throw preprocessErr
        }
      }
      setVendorNormMap(normMap)
      setUnmatchedSubVendors(unmatchedSubs)
      setUnmatchedSubNormalized(unmatchedNorm)
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
      setStage('vendor_cleanup')
      // Fire matching config suggestion in background — EDA step gives it time to load
      setMatchingConfigLoading(true)
      suggestMatchingConfig(sessionId)
        .then((suggestion) => {
          setMatchingSuggestion(suggestion)
          setDetScenarios(suggestion.deterministic_scenarios)
          setProbConfig(suggestion.probabilistic)
        })
        .catch(() => {
          setMatchingSuggestion({ deterministic_scenarios: [], probabilistic: probConfig, rationale: '' })
        })
        .finally(() => setMatchingConfigLoading(false))
    } catch (err) {
      setColumnMappingError(err instanceof Error ? err.message : 'Failed to prepare vendor data')
    } finally {
      setColumnMappingLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, probConfig])

  // ── Stage 3: Confirm vendor cleanup → EDA ────────────────────────────────────
  const handleConfirmVendorCleanup = useCallback(() => {
    setStage('eda')
  }, [])

  // ── Stage 4: EDA Continue → Reconciliation Design ───────────────────────────
  const handleEdaContinue = useCallback(() => {
    setStage('reconciliation_design')
  }, [])

  // ── Stage 5: Confirm matching config ─────────────────────────────────────────
  const handleConfirmMatchingConfig = useCallback(async () => {
    if (!sessionId) return
    setMatchingConfirming(true)
    setMatchingConfirmError(null)
    try {
      await confirmMatchingConfig(sessionId, {
        deterministic: detScenarios,
        probabilistic: probConfig,
      })
      setStage('ready')
    } catch (err) {
      setMatchingConfirmError(err instanceof Error ? err.message : 'Failed to confirm matching config')
    } finally {
      setMatchingConfirming(false)
    }
  }, [sessionId, detScenarios, probConfig])

  // ── Stage 6: Run matching ────────────────────────────────────────────────────
  const handleRunMatching = useCallback(async () => {
    if (!sessionId || !profileResponse) return
    setRunError(null)
    setIsRunning(true)
    try {
      if (Object.keys(vendorOverrides).length > 0) {
        try {
          await applyVendorOverrides(sessionId, vendorOverrides)
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 409)) throw e
        }
      }
      try { await runDeterministic(sessionId) } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e
      }
      navigate('/matching')
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Run matching failed')
    } finally {
      setIsRunning(false)
    }
  }, [sessionId, profileResponse, vendorOverrides, navigate])

  const handleGlChange = (file: File | null) => { setGlFile(file); setGlStatus(file ? 'done' : 'idle') }
  const handleSlChange = (file: File | null) => { setSlFile(file); setSlStatus(file ? 'done' : 'idle') }
  const handleVendorOverride = (key: string, value: string) => {
    setVendorOverrides((prev) => ({ ...prev, [key]: value }))
  }

  const handleChatConfigUpdate = useCallback((update: MatchingConfigUpdate) => {
    if (update.deterministic) setDetScenarios(update.deterministic as DeterministicScenarioConfig[])
    if (update.probabilistic) setProbConfig(update.probabilistic as ProbabilisticConfig)
  }, [])

  const afterColumnMapping = stage !== 'upload' && stage !== 'column_mapping'
  const afterVendorCleanup = stage === 'eda' || stage === 'reconciliation_design' || stage === 'ready'
  const afterEda           = stage === 'reconciliation_design' || stage === 'ready'

  return (
    <PageLayout title="Load & Prep Data" description="Upload your files and walk through each preparation step to set up your reconciliation.">

      {/* ── Section 1: Load & Process Data ─────────────────────────────────── */}
      <section className="space-y-4">
        <div className="grid gap-6 md:grid-cols-2">
          <Card className={whiteCardClass}>
            <CardContent className="pt-6">
              <FileDropzone label="General Ledger" value={glFile} onChange={handleGlChange} status={glStatus} />
            </CardContent>
          </Card>
          <Card className={whiteCardClass}>
            <CardContent className="pt-6">
              <FileDropzone label="Subledger" value={slFile} onChange={handleSlChange} status={slStatus} />
            </CardContent>
          </Card>
        </div>

        {hasAllFiles && stage === 'upload' && !uploadLoading && (
          <Button size="lg" variant="brand" onClick={handleProcessData}>
            Process Data
          </Button>
        )}

        {(uploadLoading || columnAnalysisLoading) && (
          <div className="flex items-center gap-2 text-sm text-[#1a1a1a]">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {uploadLoading ? 'Uploading files…' : 'Analyzing columns…'}
          </div>
        )}

        {uploadError && (
          <p className="text-sm text-destructive whitespace-pre-line">{uploadError}</p>
        )}
      </section>

      {/* ── Section 2: Column Mapping ───────────────────────────────────────── */}
      {stage !== 'upload' && (
        <div ref={columnMappingRef} className="scroll-mt-4">
          {columnAnalysis ? (
            <ColumnMappingSection
              analysis={columnAnalysis}
              sideAMap={sideAMap}
              sideBMap={sideBMap}
              onSideAChange={setSideAMap}
              onSideBChange={setSideBMap}
              onConfirm={handleConfirmColumns}
              confirming={columnMappingLoading}
              confirmingMessage={glProfile ? 'Preparing vendors…' : 'Loading statistics…'}
              error={columnMappingError}
              glStats={glProfile?.column_stats}
              slStats={slProfile?.column_stats}
            />
          ) : columnAnalysisLoading ? (
            <div className="flex items-center gap-2 text-sm text-[#1a1a1a]">
              <Loader2 className="size-4 animate-spin" aria-hidden />Analyzing columns…
            </div>
          ) : null}
        </div>
      )}

      {/* ── Section 3: Vendor Cleanup ───────────────────────────────────────── */}
      {afterColumnMapping && (
        <div ref={vendorCleanupRef} className="scroll-mt-4">
          <Card className={whiteCardClass}>
            <CardHeader>
              <CardTitle className="text-[#1a1a1a]">Vendor Cleanup</CardTitle>
              <CardDescription className="text-[#1a1a1a]">
                Vendor normalization map generated from your input files. Override the standardized
                name for any row below, then confirm to continue.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {profileError ? (
                <p className="text-sm text-destructive whitespace-pre-line">{profileError}</p>
              ) : vendorNormMap.length === 0 ? (
                <p className="text-sm text-[#1a1a1a] py-4">No vendor normalization data available.</p>
              ) : (
                <VendorPreprocessingTable
                  vendorNormMap={vendorNormMap}
                  unmatchedSubVendors={unmatchedSubVendors}
                  vendorOverrides={vendorOverrides}
                  onVendorOverride={handleVendorOverride}
                />
              )}
              {stage === 'vendor_cleanup' && !profileError && (
                <Button variant="brand" onClick={handleConfirmVendorCleanup}>
                  Confirm Vendor Cleanup
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Section 4: Exploratory Data Analytics ──────────────────────────── */}
      {afterVendorCleanup && (
        <div ref={edaRef} className="scroll-mt-4">
          <Card className={whiteCardClass}>
            <CardHeader>
              <CardTitle className="text-[#1a1a1a]">Exploratory Data Analytics</CardTitle>
              <CardDescription className="text-[#1a1a1a]">
                Key statistics and distributions for your General Ledger and Subledger files.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-8">
              {/* Cross-file BANs */}
              {profileResponse?.metrics?.cross_file && (
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

              {/* AI narrative */}
              {profileResponse?.narrative && (
                <div className="rounded-lg border border-gray-200 bg-white p-4">
                  <p className="text-xs uppercase tracking-wide text-[#1a1a1a] mb-2">Summary</p>
                  <p className="text-sm leading-relaxed whitespace-pre-line">{profileResponse.narrative}</p>
                </div>
              )}

              {/* GL BANs */}
              {glProfile && (
                <div className="space-y-4">
                  <h3 className="text-xl font-bold text-[#1a1a1a]">General Ledger</h3>
                  <BanCards profile={glProfile} />
                </div>
              )}

              {/* Subledger BANs */}
              {slProfile && (
                <div className="space-y-4">
                  <h3 className="text-xl font-bold text-[#1a1a1a]">Subledger</h3>
                  <BanCards profile={slProfile} />
                </div>
              )}

              {/* ── Charts ─────────────────────────────────────────────────── */}
              {(glVendorRowData.length > 0 || slVendorRowData.length > 0) && (() => {
                const rowMax = Math.max(
                  ...glVendorRowData.map((d) => d.value),
                  ...slVendorRowData.map((d) => d.value),
                )
                return (
                  <div className="space-y-2">
                    <h3 className="text-base font-semibold text-[#1a1a1a]">Row Count by Vendor (Top 15)</h3>
                    <div className="grid gap-6 lg:grid-cols-2">
                      {glVendorRowData.length > 0 && (
                        <div className="rounded-lg border border-gray-200 bg-white p-4">
                          <VendorBarChart
                            title="General Ledger"
                            data={glVendorRowData}
                            dataKey="value"
                            color="#98002E"
                            formatter={(v) => v.toLocaleString()}
                            xMax={rowMax}
                          />
                        </div>
                      )}
                      {slVendorRowData.length > 0 && (
                        <div className="rounded-lg border border-gray-200 bg-white p-4">
                          <VendorBarChart
                            title="Subledger"
                            data={slVendorRowData}
                            dataKey="value"
                            color="#0062B8"
                            formatter={(v) => v.toLocaleString()}
                            xMax={rowMax}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}

              {(glVendorAmtData.length > 0 || slVendorAmtData.length > 0) && (() => {
                const amtMax = Math.max(
                  ...glVendorAmtData.map((d) => d.value),
                  ...slVendorAmtData.map((d) => d.value),
                )
                return (
                  <div className="space-y-2">
                    <h3 className="text-base font-semibold text-[#1a1a1a]">Amount by Vendor (Top 15, absolute value)</h3>
                    <div className="grid gap-6 lg:grid-cols-2">
                      {glVendorAmtData.length > 0 && (
                        <div className="rounded-lg border border-gray-200 bg-white p-4">
                          <VendorBarChart
                            title="General Ledger"
                            data={glVendorAmtData}
                            dataKey="value"
                            color="#98002E"
                            formatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}`}
                            xMax={amtMax}
                          />
                        </div>
                      )}
                      {slVendorAmtData.length > 0 && (
                        <div className="rounded-lg border border-gray-200 bg-white p-4">
                          <VendorBarChart
                            title="Subledger"
                            data={slVendorAmtData}
                            dataKey="value"
                            color="#0062B8"
                            formatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}`}
                            xMax={amtMax}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}

              {(glDailyData.length > 0 || slDailyData.length > 0) && (
                <div className="space-y-2">
                  <div className="rounded-lg border border-gray-200 bg-white p-4">
                    <AmountByDayChart glData={glDailyData} slData={slDailyData} />
                  </div>
                </div>
              )}

              {/* Continue button */}
              {stage === 'eda' && (
                <div className="pt-2">
                  <Button size="lg" variant="brand" onClick={handleEdaContinue}>
                    Continue
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Section 5: Reconciliation Design ───────────────────────────────── */}
      {afterEda && (
        <div ref={reconDesignRef} className="scroll-mt-4">
          {matchingConfigLoading ? (
            <div className="flex items-center gap-2 text-sm text-[#1a1a1a]">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Generating reconciliation recommendations…
            </div>
          ) : matchingSuggestion ? (
            <MatchingConfigSection
              rationale={matchingSuggestion.rationale}
              scenarios={detScenarios}
              probConfig={probConfig}
              onScenariosChange={setDetScenarios}
              onProbChange={setProbConfig}
              onConfirm={handleConfirmMatchingConfig}
              confirming={matchingConfirming}
              error={matchingConfirmError}
              title="Reconciliation Design"
            />
          ) : null}
        </div>
      )}

      {/* ── Run Matching CTA ────────────────────────────────────────────────── */}
      {stage === 'ready' && profileResponse && (
        <footer ref={readyRef} className="flex flex-col items-start gap-4 border-t pt-6 scroll-mt-4">
          <Button size="lg" variant="brand" disabled={isRunning} onClick={handleRunMatching}>
            {isRunning ? (
              <><Loader2 className="size-4 animate-spin" aria-hidden />Starting…</>
            ) : (
              <>Run Matching<ArrowRight className="size-4" aria-hidden /></>
            )}
          </Button>
          {runError && <p className="text-sm text-destructive" role="alert">{runError}</p>}
        </footer>
      )}

      {/* AI Chat Panel */}
      {sessionId && stage !== 'upload' && (
        <ChatPanel
          sessionId={sessionId}
          matchingContext={
            (stage === 'reconciliation_design' || stage === 'ready')
              ? { deterministic: detScenarios, probabilistic: probConfig }
              : null
          }
          onConfigUpdate={
            (stage === 'reconciliation_design' || stage === 'ready') ? handleChatConfigUpdate : undefined
          }
        />
      )}
    </PageLayout>
  )
}
