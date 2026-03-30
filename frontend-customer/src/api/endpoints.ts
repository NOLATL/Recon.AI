import { apiRequest, fetchWithTimeout, ApiError } from "./apiClient"
import { API_BASE_URL } from "./apiClient"

export { ApiError }

const UPLOAD_TIMEOUT_MS = 60_000
const PROFILE_TIMEOUT_MS = 30_000

// ---------------------------------------------------------------------------
// Types (aligned with FastAPI Pydantic schemas)
// ---------------------------------------------------------------------------

export interface SessionCreateResponse {
  session_id: string
  current_state: string
}

export interface SessionStatusResponse {
  session_id: string
  current_state: string
  is_review_phase: boolean
  snapshot_count: number
  matching_summary: Record<string, number>
  matching_amount_summary: Record<string, number>
}

export interface SessionListResponse {
  session_ids: string[]
  count: number
}

export interface SnapshotInfo {
  key: string
  integrity_hash: string
}

export interface FileValidationSummary {
  file_key: string
  is_valid: boolean
  row_count: number
  columns_validated: string[]
  schema_hash: string
}

export interface UploadSuccessResponse {
  session_id: string
  state: string
  row_counts: Record<string, number>
  validation: Record<string, FileValidationSummary>
  snapshot: SnapshotInfo
}

export interface NumericDistributionSchema {
  min?: number
  max?: number
  mean?: number
  median?: number
  std?: number
  sum?: number
  null_count: number
}

export interface DateRangeSchema {
  min?: string
  max?: string
}

export interface FileProfilingSummary {
  file_key: string
  row_count: number
  null_counts: Record<string, number>
  null_percentages: Record<string, number>
  duplicate_row_count: number
  numeric_distributions: Record<string, NumericDistributionSchema>
  date_ranges: Record<string, DateRangeSchema>
  entity_distribution: Record<string, number>
}

export interface CrossFileSummarySchema {
  gl_row_count: number
  subledger_row_count: number
  row_count_delta: number
  row_count_delta_pct: number
}

export interface ProfilingMetrics {
  files: Record<string, FileProfilingSummary>
  cross_file: CrossFileSummarySchema
}

export interface ProfilingResponse {
  session_id: string
  state: string
  metrics: ProfilingMetrics
  narrative: string
  snapshot: SnapshotInfo
}

export interface PreprocessingResponse {
  session_id: string
  state: string
  normalization_summary: {
    total_unique_gl_vendors: number
    tier1_count: number
    tier2_count: number
    tier3_count: number
    threshold_used: number
    alias_version: string
  }
  vendor_normalization_map: Array<Record<string, unknown>>
  unmatched_sub_vendors: string[]
  unmatched_sub_normalized: Record<string, string>
  gl_normalized_vendor_row_distribution: Record<string, number>
  gl_normalized_vendor_amt_distribution: Record<string, number>
  sl_normalized_vendor_row_distribution: Record<string, number>
  sl_normalized_vendor_amt_distribution: Record<string, number>
  snapshot: SnapshotInfo
}

export interface ConsolidationSummary {
  deterministic_match_count: number
  probabilistic_match_count: number
  ai_match_count: number
  total_match_count: number
  residual_gl_count: number
  residual_sub_count: number
  rejected_count: number
  override_count: number
}

export interface FinalConsolidationResponse {
  session_id: string
  state: string
  summary: ConsolidationSummary
  final_matches: Array<Record<string, unknown>>
  gl_records: Array<Record<string, unknown>>
  sub_records: Array<Record<string, unknown>>
  residual_gl_records: Array<Record<string, unknown>>
  residual_sub_records: Array<Record<string, unknown>>
  rejected_matches: Array<Record<string, unknown>>
  snapshot: SnapshotInfo
}

export interface ExportFileInfo {
  filename: string
  path: string
  sha256: string
  size_bytes: number
}

export interface ExportResponse {
  session_id: string
  state: string
  export_dir: string
  exported_at: string
  files: ExportFileInfo[]
  snapshot: SnapshotInfo
}

/** localStorage key for the current reconciliation session id */
export const RECON_SESSION_ID_KEY = "recon_session_id"

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export function startSession(metadata?: Record<string, unknown>): Promise<SessionCreateResponse> {
  return apiRequest<SessionCreateResponse>("/reconciliation/start", {
    method: "POST",
    body: metadata ? { metadata } : {},
  })
}

export function listSessions(): Promise<SessionListResponse> {
  return apiRequest<SessionListResponse>("/reconciliation/sessions")
}

export function getSessionStatus(sessionId: string): Promise<SessionStatusResponse> {
  return apiRequest<SessionStatusResponse>(`/reconciliation/${sessionId}/status`)
}

export function transitionState(
  sessionId: string,
  newState: string,
  triggeredBy?: string
): Promise<{ session_id: string; previous_state: string; current_state: string; snapshot_key: string }> {
  return apiRequest(`/reconciliation/${sessionId}/transition/${newState}`, {
    method: "POST",
    body: triggeredBy != null ? { triggered_by: triggeredBy } : {},
  })
}

// ---------------------------------------------------------------------------
// Intake (upload) — requires chart_of_accounts, gl, subledger
// ---------------------------------------------------------------------------

/** Backend requires exact filenames. Use this to send with correct name. */
function fileWithName(file: File, expectedName: string): File {
  if (file.name === expectedName) return file
  return new File([file], expectedName, { type: file.type })
}

export async function uploadFiles(
  sessionId: string,
  gl: File,
  subledger: File,
  chartOfAccounts?: File | null
): Promise<UploadSuccessResponse> {
  const form = new FormData()
  form.append("gl", fileWithName(gl, "GL.csv"))
  form.append("subledger", fileWithName(subledger, "Subledger.csv"))
  if (chartOfAccounts) {
    form.append("chart_of_accounts", fileWithName(chartOfAccounts, "Chart_of_Accounts.csv"))
  }
  const res = await fetchWithTimeout(
    `${API_BASE_URL}/reconciliation/${sessionId}/upload`,
    {
      method: "POST",
      body: form,
      timeoutMs: UPLOAD_TIMEOUT_MS,
    }
  )
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(`Upload failed (${res.status})`, res.status, body)
  }
  return res.json() as Promise<UploadSuccessResponse>
}

// ---------------------------------------------------------------------------
// Profiling (profiling_routes.py: POST to run, GET to pull stored data)
// ---------------------------------------------------------------------------

/** Run profiling and advance to 'profiled' state. Requires state 'files_loaded'. */
export function runProfile(sessionId: string): Promise<ProfilingResponse> {
  return apiRequest<ProfilingResponse>(`/reconciliation/${sessionId}/profile`, {
    method: "POST",
    timeoutMs: PROFILE_TIMEOUT_MS,
  })
}

/** Get stored profiling data when session is already profiled (or later). */
export function getProfile(sessionId: string): Promise<ProfilingResponse> {
  return apiRequest<ProfilingResponse>(`/reconciliation/${sessionId}/profile`, {
    timeoutMs: PROFILE_TIMEOUT_MS,
  })
}

// ---------------------------------------------------------------------------
// Preprocessing
// ---------------------------------------------------------------------------

export function runPreprocess(sessionId: string): Promise<PreprocessingResponse> {
  return apiRequest<PreprocessingResponse>(`/reconciliation/${sessionId}/preprocess`, {
    method: "POST",
    timeoutMs: 120_000,
  })
}

export function getPreprocess(sessionId: string): Promise<PreprocessingResponse> {
  return apiRequest<PreprocessingResponse>(`/reconciliation/${sessionId}/preprocess`, {
    timeoutMs: 15_000,
  })
}

/** Apply manual vendor overrides to Vendor_Normalized before matching. */
export function applyVendorOverrides(
  sessionId: string,
  vendorOverrides: Record<string, string>
): Promise<{ status: string; applied_count: number }> {
  const filtered = Object.fromEntries(
    Object.entries(vendorOverrides).filter(([, v]) => v != null && String(v).trim() !== '')
  )
  if (Object.keys(filtered).length === 0) {
    return Promise.resolve({ status: 'ok', applied_count: 0 })
  }
  return apiRequest<{ status: string; applied_count: number }>(
    `/reconciliation/${sessionId}/preprocess/vendor_overrides`,
    {
      method: 'POST',
      body: { vendor_overrides: filtered },
      timeoutMs: 15_000,
    }
  )
}

// ---------------------------------------------------------------------------
// Deterministic (Phase 4, 4A)
// ---------------------------------------------------------------------------

export function runDeterministic(sessionId: string): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/deterministic`, {
    method: "POST",
    timeoutMs: 60_000,
  })
}

export function confirmDeterministicReview(sessionId: string): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/deterministic/review`, {
    method: "POST",
  })
}

// ---------------------------------------------------------------------------
// Probabilistic (Phase 5, 5A)
// ---------------------------------------------------------------------------

export function runProbabilistic(sessionId: string): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/probabilistic`, {
    method: "POST",
    timeoutMs: 300_000,
  })
}

export function confirmProbabilisticReview(
  sessionId: string,
  decisions: Array<{ match_id: string; decision: "accepted" | "rejected" }>
): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/probabilistic/review`, {
    method: "POST",
    body: { decisions },
  })
}

// ---------------------------------------------------------------------------
// AI (Phase 6, 6A)
// ---------------------------------------------------------------------------

export function runAi(sessionId: string): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/ai`, {
    method: "POST",
    timeoutMs: 300_000,
  })
}

export function confirmAiReview(
  sessionId: string,
  decisions: Array<{ match_id: string; decision: "accepted" | "rejected" }>
): Promise<unknown> {
  return apiRequest(`/reconciliation/${sessionId}/ai/review`, {
    method: "POST",
    body: { decisions },
  })
}

// ---------------------------------------------------------------------------
// Final consolidation
// ---------------------------------------------------------------------------

export function runConsolidate(sessionId: string): Promise<FinalConsolidationResponse> {
  return apiRequest<FinalConsolidationResponse>(`/reconciliation/${sessionId}/consolidate`, {
    method: "POST",
    timeoutMs: 30_000,
  })
}

export function getConsolidation(sessionId: string): Promise<FinalConsolidationResponse> {
  return apiRequest<FinalConsolidationResponse>(`/reconciliation/${sessionId}/consolidate`, {
    timeoutMs: 15_000,
  })
}

export function getSummaryNarrative(sessionId: string): Promise<{ narrative: string }> {
  return apiRequest<{ narrative: string }>(`/reconciliation/${sessionId}/narrative`, {
    timeoutMs: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

/** Save matches the user manually rejected on the Matched Analysis page. */
export function saveManualRejected(
  sessionId: string,
  manualRejected: { match_id: string; record_ids_A: string[]; record_ids_B: string[] }[]
): Promise<{ session_id: string; rejected_count: number; status: string }> {
  return apiRequest(
    `/reconciliation/${sessionId}/manual-rejected`,
    { method: "POST", body: { manual_rejected: manualRejected }, timeoutMs: 15_000 }
  )
}

/** Save manual GL↔Sub override links before exporting. */
export function saveManualOverrides(
  sessionId: string,
  overrides: Record<string, string[]>
): Promise<{ session_id: string; override_count: number; status: string }> {
  return apiRequest(
    `/reconciliation/${sessionId}/overrides`,
    { method: "POST", body: { overrides }, timeoutMs: 15_000 }
  )
}

export function runExport(sessionId: string): Promise<ExportResponse> {
  return apiRequest<ExportResponse>(`/reconciliation/${sessionId}/export`, {
    method: "POST",
    timeoutMs: 60_000,
  })
}

export function getExportManifest(sessionId: string): Promise<ExportResponse> {
  return apiRequest<ExportResponse>(`/reconciliation/${sessionId}/export`)
}

/** Returns the URL to download a single exported file (same origin). */
export function getExportFileDownloadUrl(sessionId: string, filename: string): string {
  return `${API_BASE_URL}/reconciliation/${sessionId}/export/files/${encodeURIComponent(filename)}`
}

/** Returns the URL to download a ZIP of the given filenames in one request. */
export function getExportZipUrl(sessionId: string, filenames: string[]): string {
  const params = new URLSearchParams({ files: filenames.join(",") })
  return `${API_BASE_URL}/reconciliation/${sessionId}/export/zip?${params}`
}

// ---------------------------------------------------------------------------
// Column Mapping (Phase 1.5 — between files_loaded and profiled)
// ---------------------------------------------------------------------------

export type ColumnRole = 'id' | 'vendor' | 'amount' | 'date' | 'entity' | 'currency' | 'ignore'

export interface ColumnSuggestion {
  column_name: string
  detected_role: ColumnRole | null
  confidence: number
  sample_values: string[]
  data_type: string
}

export interface AnalyzeColumnsResponse {
  side_a_label: string
  side_b_label: string
  side_a_suggestions: ColumnSuggestion[]
  side_b_suggestions: ColumnSuggestion[]
  analysis_narrative: string
}

export type SideColumnMap = Partial<Record<ColumnRole, string>>

export interface ConfirmColumnMappingRequest {
  column_map: {
    side_a_label: string
    side_b_label: string
    side_a: SideColumnMap
    side_b: SideColumnMap
  }
}

export function analyzeColumns(sessionId: string): Promise<AnalyzeColumnsResponse> {
  return apiRequest<AnalyzeColumnsResponse>(
    `/reconciliation/${sessionId}/analyze-columns`,
    { method: 'POST', timeoutMs: 60_000 }
  )
}

export function confirmColumnMapping(
  sessionId: string,
  body: ConfirmColumnMappingRequest
): Promise<{ session_id: string; state: string }> {
  return apiRequest(
    `/reconciliation/${sessionId}/confirm-columns`,
    { method: 'POST', body, timeoutMs: 15_000 }
  )
}

// ---------------------------------------------------------------------------
// Matching Config (Phase 3.5 — between preprocessed and deterministic)
// ---------------------------------------------------------------------------

export interface DeterministicScenarioConfig {
  scenario_id: number
  description: string
  match_fields: string[]
  date_tolerance_days: number | null
  amount_tolerance_abs: number | null
  amount_tolerance_pct: number | null
  confidence_score: number
}

export interface ProbabilisticConfig {
  weights: Record<string, number>
  threshold: number
  date_tolerance_days: number
  amount_pct_tolerance: number
  amount_abs_tolerance: number
}

export interface SuggestMatchingConfigResponse {
  deterministic_scenarios: DeterministicScenarioConfig[]
  probabilistic: ProbabilisticConfig
  rationale: string
}

export function suggestMatchingConfig(sessionId: string): Promise<SuggestMatchingConfigResponse> {
  return apiRequest<SuggestMatchingConfigResponse>(
    `/reconciliation/${sessionId}/suggest-matching-config`,
    { method: 'POST', timeoutMs: 60_000 }
  )
}

export function confirmMatchingConfig(
  sessionId: string,
  body: { deterministic: DeterministicScenarioConfig[]; probabilistic: ProbabilisticConfig }
): Promise<{ session_id: string; state: string }> {
  return apiRequest(
    `/reconciliation/${sessionId}/confirm-matching-config`,
    { method: 'POST', body, timeoutMs: 15_000 }
  )
}

export function getMatchingConfig(sessionId: string): Promise<{
  matching_config: {
    deterministic?: DeterministicScenarioConfig[]
    probabilistic?: ProbabilisticConfig
  }
}> {
  return apiRequest(`/reconciliation/${sessionId}/matching-config`, { timeoutMs: 10_000 })
}

// ---------------------------------------------------------------------------
// Adapters for existing UI (summary, unmatched, file profile display)
// ---------------------------------------------------------------------------

export interface ColumnStat {
  name: string
  data_type: "numeric" | "date" | "string"
  unique_count: number
  null_count: number
  null_pct: number
  // numeric only
  min?: number | string | null
  max?: number | string | null
  mean?: number | null
  median?: number | null
  std?: number | null
  sum?: number | null
  // string only
  max_len?: number | null
  min_len?: number | null
  blank_count?: number | null
  mode?: string | null
  // histogram
  histogram: { label: string; count: number }[]
}

/** Per-file profile shape used by LoadFiles profiling section. */
export interface FileProfile {
  row_count: number
  unique_vendors: number
  date_from: string
  date_to: string
  total_amount: number
  column_stats: ColumnStat[]
  vendor_row_distribution: Record<string, number>
  vendor_amount_distribution: Record<string, number>
  daily_amount_distribution: Record<string, number>
}

/** Map backend ProfilingResponse.metrics.files to FileProfile for GL/subledger. */
export function metricsToFileProfile(
  fileKey: "gl" | "subledger",
  metrics: ProfilingMetrics
): FileProfile | null {
  const files = metrics?.files
  if (!files || typeof files !== "object") return null
  const f =
    files[fileKey] ??
    files[fileKey === "gl" ? "GL" : "Subledger"] ??
    files[fileKey === "gl" ? "gl" : "subledger"]
  if (!f || typeof f !== "object") return null

  const fRec = f as unknown as Record<string, unknown>
  const dateRanges = fRec.date_ranges as Record<string, { min?: string; max?: string }> | undefined
  const dateRangesObj = dateRanges && typeof dateRanges === "object" ? dateRanges : {}
  const dateCol = Object.keys(dateRangesObj)[0]
  const dr = dateCol ? dateRangesObj[dateCol] : null

  const numDists = fRec.numeric_distributions as Record<string, { sum?: number }> | undefined
  const numDistsObj = numDists && typeof numDists === "object" ? numDists : {}
  const numCol = Object.keys(numDistsObj).find((k) =>
    String(k).toLowerCase().includes("amount")
  )
  const nd = numCol ? numDistsObj[numCol] : null

  const uniqueVendors = typeof fRec.unique_vendor_count === "number"
    ? fRec.unique_vendor_count as number
    : 0

  const rowCount = typeof fRec.row_count === "number"
    ? fRec.row_count as number
    : 0

  // Build ColumnStat array from column_profiles (new backend field)
  const rawProfiles = fRec.column_profiles as Record<string, Record<string, unknown>> | undefined
  const column_stats: ColumnStat[] = rawProfiles
    ? Object.entries(rawProfiles).map(([name, p]) => ({
        name,
        data_type:    (p.data_type as ColumnStat["data_type"]) ?? "string",
        unique_count: (p.unique_count as number) ?? 0,
        null_count:   (p.null_count as number) ?? 0,
        null_pct:     (p.null_pct as number) ?? 0,
        min:          p.min as number | string | null | undefined,
        max:          p.max as number | string | null | undefined,
        mean:         p.mean as number | null | undefined,
        median:       p.median as number | null | undefined,
        std:          p.std as number | null | undefined,
        sum:          p.sum as number | null | undefined,
        max_len:      p.max_len as number | null | undefined,
        min_len:      p.min_len as number | null | undefined,
        blank_count:  p.blank_count as number | null | undefined,
        mode:         p.mode as string | null | undefined,
        histogram:    (p.histogram as { label: string; count: number }[]) ?? [],
      }))
    : []

  return {
    row_count: rowCount,
    unique_vendors: uniqueVendors,
    date_from: (dr && "min" in dr ? dr.min : null) ?? "",
    date_to: (dr && "max" in dr ? dr.max : null) ?? "",
    total_amount: (nd && "sum" in nd ? nd.sum : null) ?? 0,
    column_stats,
    vendor_row_distribution: (fRec.vendor_row_distribution as Record<string, number>) ?? {},
    vendor_amount_distribution: (fRec.vendor_amount_distribution as Record<string, number>) ?? {},
    daily_amount_distribution: (fRec.daily_amount_distribution as Record<string, number>) ?? {},
  }
}

export interface SummaryResults {
  match_rate: number
  matched_amount: number
  unmatched_amount: number
}

/** Derive SummaryResults from FinalConsolidationResponse. */
export function consolidationToSummary(res: FinalConsolidationResponse): SummaryResults {
  const s = res.summary
  const totalRecords =
    s.total_match_count + s.residual_gl_count + s.residual_sub_count || 1
  const matchRate = s.total_match_count / totalRecords
  const matchedAmount = res.gl_records.reduce(
    (sum, r) => sum + (Number((r as Record<string, unknown>).amount) || 0),
    0
  )
  const unmatchedAmount =
    res.residual_gl_records.reduce(
      (sum, r) => sum + (Number((r as Record<string, unknown>).amount) || 0),
      0
    ) +
    res.residual_sub_records.reduce(
      (sum, r) => sum + (Number((r as Record<string, unknown>).amount) || 0),
      0
    )
  return {
    match_rate: matchRate,
    matched_amount: matchedAmount,
    unmatched_amount: unmatchedAmount,
  }
}

export interface UnmatchedRecord {
  entity: string
  vendor: string
  date: string
  amount: number
}

/** Flatten residual GL + subledger records into UnmatchedRecord[] for UI. */
export function consolidationToUnmatched(res: FinalConsolidationResponse): UnmatchedRecord[] {
  const toRecord = (r: Record<string, unknown>): UnmatchedRecord => ({
    entity: String(r.entity ?? ""),
    vendor: String(r.vendor_name ?? r.vendor ?? ""),
    date: String(r.transaction_date ?? r.date ?? ""),
    amount: Number(r.amount ?? 0),
  })
  const glRows = res.residual_gl_records as Record<string, unknown>[]
  const subRows = res.residual_sub_records as Record<string, unknown>[]
  return [
    ...glRows.map(toRecord),
    ...subRows.map(toRecord),
  ]
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface MatchingConfigUpdate {
  deterministic?: DeterministicScenarioConfig[]
  probabilistic?: ProbabilisticConfig
}

export interface ChatResponse {
  session_id: string
  reply: string
  rich_content?: unknown
  config_update?: MatchingConfigUpdate | null
}

export function chatMessage(
  sessionId: string,
  message: string,
  history: ChatMessage[],
  matchingContext?: { deterministic: DeterministicScenarioConfig[]; probabilistic: ProbabilisticConfig } | null
): Promise<ChatResponse> {
  return apiRequest<ChatResponse>(
    `/reconciliation/${sessionId}/chat`,
    {
      method: 'POST',
      body: {
        message,
        conversation_history: history,
        matching_context: matchingContext ?? null,
      },
      timeoutMs: 30_000,
    }
  )
}
