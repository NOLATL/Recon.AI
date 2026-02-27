# AI Reconciliation Platform --- Architecture Constraints

*Last Updated: 2026-02-26*

------------------------------------------------------------------------

## Core Design Principles

-   API-first architecture
-   Backend-owned state machine
-   Strict forward-only state transitions
-   Snapshot written BEFORE every state transition
-   No backward navigation
-   No recomputation during review phases
-   Deterministic layer is authoritative
-   Probabilistic layer is additive
-   AI layer is advisory only
-   Immutable phase-level snapshots
-   All state mutation must occur inside explicit transition functions
-   No silent data mutation

------------------------------------------------------------------------

## Global State Machine

Valid States:

1.  initialized
2.  files_loaded
3.  profiled
4.  preprocessed
5.  deterministic_complete
6.  deterministic_review_complete
7.  probabilistic_complete
8.  probabilistic_review_complete
9.  ai_suggested
10. ai_review_complete
11. final_consolidated
12. finalized

Rules:

-   Transitions must be explicitly validated.
-   No skipping states.
-   Snapshot must be written immediately before advancing state.
-   Illegal transitions must raise errors.

------------------------------------------------------------------------

## Snapshot Requirements

Each snapshot must contain:

-   Deep copy of state data
-   Config metadata (weights, thresholds, AI model)
-   Row counts
-   Integrity hash
-   Narrative (if applicable)
-   Timestamp

Guarantees:

-   Reproducible
-   Immutable
-   Auditable

------------------------------------------------------------------------

## Runtime Object Contract

The runtime container must include:

-   session_id
-   current_state
-   raw_data (chart_of_accounts, gl, subledger)
-   clean_data
-   vendor_normalization_map
-   profiling
-   matching (deterministic, probabilistic, ai_suggested, final,
    rejected)
-   residual_pool
-   snapshots
-   config (weights, thresholds, ai_model, vendor_nlp_threshold)

MVP storage: In-memory dict keyed by session_id. Future: Redis or
database-backed persistence.

------------------------------------------------------------------------

## Vendor Normalization Governance (Phase 3)

Three-tier pipeline:

1.  Deterministic preprocessing

    -   Lowercasing
    -   Punctuation removal
    -   Corporate suffix stripping
    -   Stopword removal
    -   Alias table

    match_source = "preprocessing"

2.  NLP similarity matching

    -   RapidFuzz or cosine similarity
    -   Threshold default = 0.90

    match_source = "nlp" similarity_score required

3.  AI residual resolution

    -   Advisory only
    -   Confidence score logged
    -   Model + prompt version stored in snapshot

    match_source = "ai" ai_confidence_score required

Rules:

-   One mapping row per distinct original vendor
-   Mapping table immutable after snapshot
-   Vendor_Normalized column propagated to GL and Subledger
-   Original vendor preserved for audit

------------------------------------------------------------------------

## Deterministic Matching Rules

-   Authoritative layer
-   No overrides in v1
-   Once matched, records removed from pool
-   Confidence score assigned
-   No mutation during review phase

------------------------------------------------------------------------

## Probabilistic Matching Rules

Similarity formula:

0.40 \* vendor_similarity + 0.35 \* amount_similarity + 0.15 \*
date_similarity + 0.10 \* entity_similarity

Rules:

-   Threshold stored in runtime config
-   Max grouping size: 5
-   Rejected matches returned to residual pool
-   No recomputation during review

------------------------------------------------------------------------

## AI Matching Rules

-   Advisory only
-   No automatic acceptance
-   No dataset mutation until human approval
-   Model metadata stored in snapshot
-   Ranked by materiality then confidence

------------------------------------------------------------------------

## Global Guarantees

-   Deterministic layer immutable
-   Overrides preserved
-   Audit trace reproducible
-   Clear separation between frontend and backend
-   No business logic in API route files
-   All mutation inside service layer
-   All transitions routed through state machine module

------------------------------------------------------------------------

## Claude Code Usage Rules

When continuing development:

-   Always specify current phase.
-   Do not modify prior phases unless explicitly requested.
-   Do not merge deterministic and probabilistic logic.
-   Do not bypass snapshot creation.
-   Refactor only when requested.

------------------------------------------------------------------------

This file exists to re-anchor Claude Code sessions after token resets.
