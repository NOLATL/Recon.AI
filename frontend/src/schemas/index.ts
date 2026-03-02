import { z } from 'zod'

// ── Primitives / reused ────────────────────────────────────────────────────────

export const SnapshotInfoSchema = z.object({
  key: z.string(),
  integrity_hash: z.string(),
})
export type SnapshotInfo = z.infer<typeof SnapshotInfoSchema>

export const ReconciliationStateSchema = z.enum([
  'initialized',
  'files_loaded',
  'profiled',
  'preprocessed',
  'deterministic_complete',
  'deterministic_review_complete',
  'probabilistic_complete',
  'probabilistic_review_complete',
  'ai_suggested',
  'ai_review_complete',
  'final_consolidated',
  'finalized',
])
export type ReconciliationState = z.infer<typeof ReconciliationStateSchema>

export const ALL_STATES: ReconciliationState[] = [
  'initialized',
  'files_loaded',
  'profiled',
  'preprocessed',
  'deterministic_complete',
  'deterministic_review_complete',
  'probabilistic_complete',
  'probabilistic_review_complete',
  'ai_suggested',
  'ai_review_complete',
  'final_consolidated',
  'finalized',
]

// ── Sessions ───────────────────────────────────────────────────────────────────

export const SessionCreateResponseSchema = z.object({
  session_id: z.string(),
  current_state: z.string(),
})
export type SessionCreateResponse = z.infer<typeof SessionCreateResponseSchema>

export const SessionListResponseSchema = z.object({
  session_ids: z.array(z.string()),
  count: z.number(),
})
export type SessionListResponse = z.infer<typeof SessionListResponseSchema>

export const SessionStatusResponseSchema = z.object({
  session_id: z.string(),
  current_state: ReconciliationStateSchema,
  is_review_phase: z.boolean(),
  snapshot_count: z.number(),
  matching_summary: z.record(z.number()),
})
export type SessionStatusResponse = z.infer<typeof SessionStatusResponseSchema>

// ── Upload ─────────────────────────────────────────────────────────────────────

export const FileValidationSummarySchema = z.object({
  file_key: z.string(),
  is_valid: z.boolean(),
  row_count: z.number(),
  columns_validated: z.array(z.string()),
  schema_hash: z.string(),
})
export type FileValidationSummary = z.infer<typeof FileValidationSummarySchema>

export const UploadSuccessResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  row_counts: z.record(z.number()),
  validation: z.record(FileValidationSummarySchema),
  snapshot: SnapshotInfoSchema,
})
export type UploadSuccessResponse = z.infer<typeof UploadSuccessResponseSchema>

// ── Profiling ──────────────────────────────────────────────────────────────────

export const NumericDistributionSchema = z.object({
  min: z.number().nullable(),
  max: z.number().nullable(),
  mean: z.number().nullable(),
  median: z.number().nullable(),
  std: z.number().nullable(),
  sum: z.number().nullable(),
  null_count: z.number(),
})
export type NumericDistribution = z.infer<typeof NumericDistributionSchema>

export const DateRangeSchema = z.object({
  min: z.string().nullable(),
  max: z.string().nullable(),
})
export type DateRange = z.infer<typeof DateRangeSchema>

export const FileProfilingSummarySchema = z.object({
  file_key: z.string(),
  row_count: z.number(),
  null_counts: z.record(z.number()),
  null_percentages: z.record(z.number()),
  duplicate_row_count: z.number(),
  numeric_distributions: z.record(NumericDistributionSchema),
  date_ranges: z.record(DateRangeSchema),
  entity_distribution: z.record(z.number()),
})
export type FileProfilingSummary = z.infer<typeof FileProfilingSummarySchema>

export const CrossFileSummarySchema = z.object({
  gl_row_count: z.number(),
  subledger_row_count: z.number(),
  row_count_delta: z.number(),
  row_count_delta_pct: z.number(),
})
export type CrossFileSummary = z.infer<typeof CrossFileSummarySchema>

export const ProfilingMetricsSchema = z.object({
  files: z.record(FileProfilingSummarySchema),
  cross_file: CrossFileSummarySchema,
})
export type ProfilingMetrics = z.infer<typeof ProfilingMetricsSchema>

export const ProfilingResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  metrics: ProfilingMetricsSchema,
  narrative: z.string(),
  snapshot: SnapshotInfoSchema,
})
export type ProfilingResponse = z.infer<typeof ProfilingResponseSchema>

// ── Preprocessing ─────────────────────────────────────────────────────────────

export const NormalizationSummarySchema = z.object({
  total_unique_gl_vendors: z.number(),
  tier1_count: z.number(),
  tier2_count: z.number(),
  tier3_count: z.number(),
  threshold_used: z.number(),
  alias_version: z.string(),
})
export type NormalizationSummary = z.infer<typeof NormalizationSummarySchema>

export const NormalizationEntrySchema = z.object({
  original_vendor: z.string(),
  normalized_vendor: z.string(),
  matched_to: z.string().nullable(),
  match_source: z.string(),
  similarity_score: z.number().nullable(),
  ai_confidence_score: z.number().nullable(),
})
export type NormalizationEntry = z.infer<typeof NormalizationEntrySchema>

export const PreprocessingResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  normalization_summary: NormalizationSummarySchema,
  vendor_normalization_map: z.array(NormalizationEntrySchema),
  snapshot: SnapshotInfoSchema,
})
export type PreprocessingResponse = z.infer<typeof PreprocessingResponseSchema>

// ── Deterministic ─────────────────────────────────────────────────────────────

export const MatchRecordSchema = z.object({
  match_id: z.string(),
  record_ids_A: z.array(z.string()),
  record_ids_B: z.array(z.string()),
  scenario_id: z.number(),
  scenario_description: z.string(),
  confidence_score: z.number(),
  grouping_type: z.string(),
  user_status: z.string(),
  override_flag: z.boolean(),
})
export type MatchRecord = z.infer<typeof MatchRecordSchema>

export const ScenarioAmountSummarySchema = z.object({
  scenario_id: z.number(),
  match_count: z.number(),
  total_gl_amount: z.number(),
  total_sub_amount: z.number(),
})
export type ScenarioAmountSummary = z.infer<typeof ScenarioAmountSummarySchema>

export const DeterministicSummarySchema = z.object({
  total_gl_records: z.number(),
  total_sub_records: z.number(),
  matched_gl_records: z.number(),
  matched_sub_records: z.number(),
  unmatched_gl_records: z.number(),
  unmatched_sub_records: z.number(),
  match_count: z.number(),
  scenario_counts: z.record(z.number()),
  total_matched_gl_amount: z.number(),
  total_matched_sub_amount: z.number(),
  scenario_amount_summaries: z.array(ScenarioAmountSummarySchema),
})
export type DeterministicSummary = z.infer<typeof DeterministicSummarySchema>

export const DeterministicResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  summary: DeterministicSummarySchema,
  matches: z.array(MatchRecordSchema),
  gl_records: z.array(z.record(z.unknown())),
  sub_records: z.array(z.record(z.unknown())),
  residual_gl_records: z.array(z.record(z.unknown())),
  residual_sub_records: z.array(z.record(z.unknown())),
  snapshot: SnapshotInfoSchema,
})
export type DeterministicResponse = z.infer<typeof DeterministicResponseSchema>

export const DeterministicReviewResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  deterministic_match_count: z.number(),
  residual_gl_count: z.number(),
  residual_sub_count: z.number(),
  snapshot: SnapshotInfoSchema,
})
export type DeterministicReviewResponse = z.infer<
  typeof DeterministicReviewResponseSchema
>

// ── Probabilistic ─────────────────────────────────────────────────────────────

export const ProbabilisticMatchSchema = z.object({
  match_id: z.string(),
  record_ids_A: z.array(z.string()),
  record_ids_B: z.array(z.string()),
  final_similarity: z.number(),
  component_scores: z.record(z.number()),
  grouping_type: z.string(),
  user_status: z.string(),
  override_flag: z.boolean(),
})
export type ProbabilisticMatch = z.infer<typeof ProbabilisticMatchSchema>

export const ProbabilisticSummarySchema = z.object({
  total_gl_records: z.number(),
  total_sub_records: z.number(),
  matched_gl_records: z.number(),
  matched_sub_records: z.number(),
  unmatched_gl_records: z.number(),
  unmatched_sub_records: z.number(),
  match_count: z.number(),
  threshold_used: z.number(),
  weights_used: z.record(z.number()),
})
export type ProbabilisticSummary = z.infer<typeof ProbabilisticSummarySchema>

export const ProbabilisticResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  summary: ProbabilisticSummarySchema,
  matches: z.array(ProbabilisticMatchSchema),
  gl_pool_records: z.array(z.record(z.unknown())),
  sub_pool_records: z.array(z.record(z.unknown())),
  snapshot: SnapshotInfoSchema,
})
export type ProbabilisticResponse = z.infer<typeof ProbabilisticResponseSchema>

export const MatchDecisionSchema = z.object({
  match_id: z.string(),
  decision: z.enum(['accepted', 'rejected']),
})
export type MatchDecision = z.infer<typeof MatchDecisionSchema>

export const ProbabilisticReviewRequestSchema = z.object({
  decisions: z.array(MatchDecisionSchema),
})
export type ProbabilisticReviewRequest = z.infer<
  typeof ProbabilisticReviewRequestSchema
>

export const ProbabilisticReviewResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  accepted_count: z.number(),
  rejected_count: z.number(),
  snapshot: SnapshotInfoSchema,
})
export type ProbabilisticReviewResponse = z.infer<
  typeof ProbabilisticReviewResponseSchema
>

// ── AI ────────────────────────────────────────────────────────────────────────

export const AIMatchSchema = z.object({
  match_id: z.string(),
  record_ids_A: z.array(z.string()),
  record_ids_B: z.array(z.string()),
  ai_confidence_score: z.number(),
  materiality: z.number(),
  supporting_features: z.record(z.unknown()),
  reasoning_narrative: z.string(),
  grouping_type: z.string(),
  user_status: z.string(),
  override_flag: z.boolean(),
})
export type AIMatch = z.infer<typeof AIMatchSchema>

export const AISummarySchema = z.object({
  total_residual_gl: z.number(),
  total_residual_sub: z.number(),
  suggestion_count: z.number(),
  model_used: z.string(),
  prompt_version: z.string(),
})
export type AISummary = z.infer<typeof AISummarySchema>

export const AIResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  summary: AISummarySchema,
  suggestions: z.array(AIMatchSchema),
  gl_pool_records: z.array(z.record(z.unknown())),
  sub_pool_records: z.array(z.record(z.unknown())),
  snapshot: SnapshotInfoSchema,
})
export type AIResponse = z.infer<typeof AIResponseSchema>

export const AIMatchDecisionSchema = z.object({
  match_id: z.string(),
  decision: z.enum(['accepted', 'rejected']),
})
export type AIMatchDecision = z.infer<typeof AIMatchDecisionSchema>

export const AIReviewRequestSchema = z.object({
  decisions: z.array(AIMatchDecisionSchema),
})
export type AIReviewRequest = z.infer<typeof AIReviewRequestSchema>

export const AIReviewResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  accepted_count: z.number(),
  rejected_count: z.number(),
  snapshot: SnapshotInfoSchema,
})
export type AIReviewResponse = z.infer<typeof AIReviewResponseSchema>

// ── Consolidation ─────────────────────────────────────────────────────────────

export const ConsolidationSummarySchema = z.object({
  deterministic_match_count: z.number(),
  probabilistic_match_count: z.number(),
  ai_match_count: z.number(),
  total_match_count: z.number(),
  residual_gl_count: z.number(),
  residual_sub_count: z.number(),
  rejected_count: z.number(),
  override_count: z.number(),
})
export type ConsolidationSummary = z.infer<typeof ConsolidationSummarySchema>

export const FinalConsolidationResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  summary: ConsolidationSummarySchema,
  final_matches:        z.array(z.record(z.unknown())),
  gl_records:           z.array(z.record(z.unknown())),
  sub_records:          z.array(z.record(z.unknown())),
  residual_gl_records:  z.array(z.record(z.unknown())),
  residual_sub_records: z.array(z.record(z.unknown())),
  rejected_matches:     z.array(z.record(z.unknown())),
  snapshot: SnapshotInfoSchema,
})
export type FinalConsolidationResponse = z.infer<
  typeof FinalConsolidationResponseSchema
>

// ── Export ────────────────────────────────────────────────────────────────────

export const ExportFileSchema = z.object({
  filename: z.string(),
  path: z.string(),
  sha256: z.string(),
  size_bytes: z.number(),
})
export type ExportFile = z.infer<typeof ExportFileSchema>

export const ExportResponseSchema = z.object({
  session_id: z.string(),
  state: z.string(),
  export_dir: z.string(),
  exported_at: z.string(),
  files: z.array(ExportFileSchema),
  snapshot: SnapshotInfoSchema,
})
export type ExportResponse = z.infer<typeof ExportResponseSchema>

// ── Snapshots ─────────────────────────────────────────────────────────────────

export const SnapshotSummarySchema = z.object({
  pre_transition_state: z.string(),
  captured_at: z.string(),
  triggered_by: z.string(),
  integrity_hash: z.string(),
  session_id: z.string().nullable().optional(),
})
export type SnapshotSummary = z.infer<typeof SnapshotSummarySchema>

export const SnapshotListResponseSchema = z.object({
  session_id: z.string(),
  snapshots: z.array(SnapshotSummarySchema),
  count: z.number(),
})
export type SnapshotListResponse = z.infer<typeof SnapshotListResponseSchema>

export const SnapshotDetailResponseSchema = z.object({
  pre_transition_state: z.string(),
  captured_at: z.string(),
  triggered_by: z.string(),
  integrity_hash: z.string(),
  session_id: z.string().nullable(),
  runtime_snapshot: z.record(z.unknown()),
})
export type SnapshotDetailResponse = z.infer<typeof SnapshotDetailResponseSchema>
