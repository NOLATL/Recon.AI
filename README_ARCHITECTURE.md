# AI Reconciliation Platform

## System Architecture --- FastAPI + React

------------------------------------------------------------------------

# 1️⃣ Objective

Build a forward-only, API-driven reconciliation engine that:

-   Normalizes vendor identities using deterministic, NLP, and
    AI-assisted resolution
-   Executes deterministic and probabilistic reconciliation layers
-   Preserves full audit traceability via immutable snapshots
-   Produces export-ready, audit-grade outputs (CSV + PDF)

The system enforces deterministic authority, probabilistic augmentation,
and AI advisory assistance --- without silent mutation or backward state
transitions.

------------------------------------------------------------------------

# 2️⃣ Architectural Principles

## Design Pillars

-   API-first architecture
-   Backend-owned state machine
-   Forward-only transitions
-   Immutable phase-level snapshots
-   Deterministic authority layer
-   Probabilistic additive layer
-   AI advisory layer (non-authoritative)
-   No recomputation during review phases
-   No backward navigation
-   Human governance with preserved overrides
-   Full audit reproducibility

------------------------------------------------------------------------

# 3️⃣ Overarching System Architecture

## Frontend

-   React + Tailwind
-   Handles file upload, review workflows, visualization, and exports

## Backend

-   FastAPI (Uvicorn runtime)
-   Owns state machine, transformations, matching engines, snapshots,
    audit logs, and output generation

## Deployment

-   Backend → Azure App Service (Docker container)
-   Frontend → Azure Static Web Apps
-   Storage (Phase 2+) → Azure Blob Storage + optional DB

------------------------------------------------------------------------

# 4️⃣ Global State Machine

Valid States:

initialized\
files_loaded\
profiled\
preprocessed\
deterministic_complete\
deterministic_review_complete\
probabilistic_complete\
probabilistic_review_complete\
ai_suggested\
ai_review_complete\
final_consolidated\
finalized

### State Rules

-   Strict forward-only transitions
-   Snapshot written before every transition
-   State validated on every API call
-   No mutation outside transition functions
-   No recomputation during review states

------------------------------------------------------------------------

# 5️⃣ Runtime Container (Backend-Owned)

``` python
runtime = {
    "session_id": str,
    "current_state": str,
    "raw_data": {
        "chart_of_accounts": DataFrame,
        "gl": DataFrame,
        "subledger": DataFrame
    },
    "clean_data": {},
    "vendor_normalization_map": [],
    "profiling": {},
    "matching": {
        "deterministic": [],
        "probabilistic": [],
        "ai_suggested": [],
        "final": [],
        "rejected": []
    },
    "residual_pool": {},
    "snapshots": {},
    "config": {
        "weights": {},
        "threshold": None,
        "ai_model": None,
        "vendor_nlp_threshold": 0.90
    }
}
```

------------------------------------------------------------------------

# 6️⃣ Vendor Normalization (Phase 3 Overview)

## Tier 1 --- Deterministic Preprocessing

-   Lowercasing
-   Punctuation removal
-   Whitespace normalization
-   Corporate suffix stripping
-   Stopword removal
-   Abbreviation expansion
-   Explicit alias table

Tagged as: `match_source = "preprocessing"`

## Tier 2 --- NLP Similarity Matching

-   Token normalization
-   Token sorting
-   RapidFuzz / cosine similarity
-   Threshold ≥ 0.90 → auto-normalize

Tagged as: `match_source = "nlp"`

## Tier 3 --- AI Residual Resolution

-   AI suggests canonical label
-   Confidence score logged
-   No automatic mutation

Tagged as: `match_source = "ai"`

------------------------------------------------------------------------

# 7️⃣ Snapshot Guarantees

Each snapshot contains: - Deep copy of state data - Config metadata -
Row counts - Integrity hash - Narrative (if applicable) - Timestamp

Guarantees: - Immutable - Reproducible - Auditable

------------------------------------------------------------------------

# 8️⃣ Final Outputs

### CSV

-   Final accepted matches
-   Residual unmatched
-   Rejected matches
-   Full audit log

### PDF

-   Executive summary
-   Reconciliation statistics
-   Override summary
-   AI narrative insights

------------------------------------------------------------------------

# 9️⃣ CI/CD Flow

VS Code\
↓\
Git Commit\
↓\
Push to GitHub\
↓\
Azure builds container\
↓\
FastAPI runs\
↓\
React build hosted\
↓\
API requests processed\
↓\
Dashboard rendered
