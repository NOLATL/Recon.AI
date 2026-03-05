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
  chartOfAccounts: File,
  gl: File,
  subledger: File
): Promise<UploadSuccessResponse> {
  const form = new FormData()
  form.append("chart_of_accounts", fileWithName(chartOfAccounts, "Chart_of_Accounts.csv"))
  form.append("gl", fileWithName(gl, "GL.csv"))
  form.append("subledger", fileWithName(subledger, "Subledger.csv"))
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

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Adapters for existing UI (summary, unmatched, file profile display)
// ---------------------------------------------------------------------------

/** Per-file profile shape used by LoadFiles profiling section. */
export interface FileProfile {
  row_count: number
  unique_vendors: number
  date_from: string
  date_to: string
  total_amount: number
  columns: { name: string; type: string; buckets?: { label: string; count: number }[] }[]
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

  const dateRanges = (f as Record<string, unknown>).date_ranges as Record<string, { min?: string; max?: string }> | undefined
  const dateRangesObj = dateRanges && typeof dateRanges === "object" ? dateRanges : {}
  const dateCol = Object.keys(dateRangesObj)[0]
  const dr = dateCol ? dateRangesObj[dateCol] : null

  const numDists = (f as Record<string, unknown>).numeric_distributions as Record<string, { sum?: number }> | undefined
  const numDistsObj = numDists && typeof numDists === "object" ? numDists : {}
  const numCol = Object.keys(numDistsObj).find((k) =>
    String(k).toLowerCase().includes("amount")
  )
  const nd = numCol ? numDistsObj[numCol] : null

  const entityDist = (f as Record<string, unknown>).entity_distribution as Record<string, number> | undefined
  const entityDistObj = entityDist && typeof entityDist === "object" ? entityDist : {}
  const uniqueVendors = Object.keys(entityDistObj).length || 0

  const nullCounts = (f as Record<string, unknown>).null_counts as Record<string, number> | undefined
  const nullCountsObj = nullCounts && typeof nullCounts === "object" ? nullCounts : {}

  const columns: FileProfile["columns"] = [
    ...Object.entries(numDistsObj).map(([name]) => ({
      name,
      type: "numeric" as const,
      buckets: [] as { label: string; count: number }[],
    })),
    ...Object.entries(dateRangesObj).map(([name]) => ({
      name,
      type: "date" as const,
      buckets: [] as { label: string; count: number }[],
    })),
  ]
  if (columns.length === 0 && Object.keys(nullCountsObj).length > 0) {
    columns.push(
      ...Object.entries(nullCountsObj).map(([name]) => ({
        name,
        type: "string" as const,
        buckets: [] as { label: string; count: number }[],
      }))
    )
  }

  const rowCount = typeof (f as Record<string, unknown>).row_count === "number"
    ? (f as Record<string, number>).row_count
    : 0

  return {
    row_count: rowCount,
    unique_vendors: uniqueVendors,
    date_from: (dr && "min" in dr ? dr.min : null) ?? "",
    date_to: (dr && "max" in dr ? dr.max : null) ?? "",
    total_amount: (nd && "sum" in nd ? nd.sum : null) ?? 0,
    columns,
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
