import { apiClient } from './client'
import type {
  SessionCreateResponse,
  SessionListResponse,
  SessionStatusResponse,
  UploadSuccessResponse,
  ProfilingResponse,
  PreprocessingResponse,
  DeterministicResponse,
  DeterministicReviewResponse,
  ProbabilisticResponse,
  ProbabilisticReviewResponse,
  ProbabilisticReviewRequest,
  AIResponse,
  AIReviewResponse,
  AIReviewRequest,
  FinalConsolidationResponse,
  ExportResponse,
  SnapshotListResponse,
  SnapshotDetailResponse,
} from '@/schemas'

const r = (sessionId: string) => `/reconciliation/${sessionId}`

// ── Sessions ───────────────────────────────────────────────────────────────────

export const startSession = () =>
  apiClient.post<SessionCreateResponse>('/reconciliation/start', {})

export const listSessions = () =>
  apiClient.get<SessionListResponse>('/reconciliation/sessions')

export const getSessionStatus = (sessionId: string) =>
  apiClient.get<SessionStatusResponse>(`${r(sessionId)}/status`)

// ── Health ────────────────────────────────────────────────────────────────────

export const getHealth = () =>
  apiClient.get<Record<string, unknown>>('/health')

// ── Phase endpoints ───────────────────────────────────────────────────────────

export const uploadFiles = (
  sessionId: string,
  chartOfAccounts: File,
  gl: File,
  subledger: File,
) => {
  const fd = new FormData()
  fd.append('chart_of_accounts', chartOfAccounts)
  fd.append('gl', gl)
  fd.append('subledger', subledger)
  return apiClient.postForm<UploadSuccessResponse>(`${r(sessionId)}/upload`, fd)
}

export const runProfile = (sessionId: string) =>
  apiClient.post<ProfilingResponse>(`${r(sessionId)}/profile`)

export const runPreprocess = (sessionId: string) =>
  apiClient.post<PreprocessingResponse>(`${r(sessionId)}/preprocess`)

export const runDeterministic = (sessionId: string) =>
  apiClient.post<DeterministicResponse>(`${r(sessionId)}/deterministic`)

export const confirmDeterministicReview = (sessionId: string) =>
  apiClient.post<DeterministicReviewResponse>(
    `${r(sessionId)}/deterministic/review`,
  )

export const runProbabilistic = (sessionId: string) =>
  apiClient.post<ProbabilisticResponse>(`${r(sessionId)}/probabilistic`)

export const confirmProbabilisticReview = (
  sessionId: string,
  body: ProbabilisticReviewRequest,
) =>
  apiClient.post<ProbabilisticReviewResponse>(
    `${r(sessionId)}/probabilistic/review`,
    body,
  )

export const runAI = (sessionId: string) =>
  apiClient.post<AIResponse>(`${r(sessionId)}/ai`)

export const confirmAIReview = (sessionId: string, body: AIReviewRequest) =>
  apiClient.post<AIReviewResponse>(`${r(sessionId)}/ai/review`, body)

export const runConsolidate = (sessionId: string) =>
  apiClient.post<FinalConsolidationResponse>(`${r(sessionId)}/consolidate`)

export const runExport = (sessionId: string) =>
  apiClient.post<ExportResponse>(`${r(sessionId)}/export`)

// ── Snapshots ─────────────────────────────────────────────────────────────────

export const listSnapshots = (sessionId: string) =>
  apiClient.get<SnapshotListResponse>(`${r(sessionId)}/snapshots`)

export const getSnapshot = (sessionId: string, phaseName: string) =>
  apiClient.get<SnapshotDetailResponse>(
    `${r(sessionId)}/snapshots/${encodeURIComponent(phaseName)}`,
  )
