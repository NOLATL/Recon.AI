# AI Reconciliation Engine — Frontend

React + TypeScript frontend for the AI Reconciliation Engine. Calls the FastAPI backend to run a
forward-only reconciliation workflow end-to-end.

## Prerequisites

- Node.js 18+
- The backend running at `http://localhost:8000` (see `/src/api/main.py`)

## Quick Start

```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Copy and configure environment
cp .env.example .env
# Edit .env if your API runs at a different address

# 3. Start dev server
npm run dev
```

Open http://localhost:5173 in your browser.

## Required Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the FastAPI backend |

Create a `.env` file in the `frontend/` directory:

```
VITE_API_BASE_URL=http://localhost:8000
```

## Build for Production

```bash
npm run build    # outputs to frontend/dist/
npm run preview  # preview the production build locally
```

## Project Structure

```
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts          # Fetch wrapper with typed error classes
│   │   └── endpoints.ts       # Typed helper per API endpoint
│   ├── schemas/
│   │   └── index.ts           # Zod schemas for all API request/response types
│   ├── pages/
│   │   ├── LandingPage.tsx    # / — session list + start new session
│   │   └── SessionDashboard.tsx  # /sessions/:sessionId — main workflow
│   ├── components/
│   │   ├── StateMachineTimeline.tsx   # Visual state progress bar
│   │   ├── HealthIndicator.tsx        # GET /health badge
│   │   ├── ErrorDisplay.tsx           # 409 / 422 / generic error renderer
│   │   ├── JsonViewer.tsx             # JSON pre-formatted viewer
│   │   ├── SnapshotPanel.tsx          # Snapshot sidebar
│   │   ├── MatchingSummaryBadges.tsx  # Bucket count badges
│   │   └── steps/
│   │       ├── UploadStep.tsx               # Phase 0→1: upload 3 CSVs
│   │       ├── ProfileStep.tsx              # Phase 1→2: data profiling
│   │       ├── PreprocessStep.tsx           # Phase 2→3: vendor normalization
│   │       ├── DeterministicStep.tsx        # Phase 3→4: deterministic matching
│   │       ├── DeterministicReviewStep.tsx  # Phase 4→4A: confirm review
│   │       ├── ProbabilisticStep.tsx        # Phase 4A→5: fuzzy matching
│   │       ├── ProbabilisticReviewStep.tsx  # Phase 5→5A: accept/reject UI
│   │       ├── AIStep.tsx                   # Phase 5A→6: AI suggestions
│   │       ├── AIReviewStep.tsx             # Phase 6→6A: AI accept/reject UI
│   │       ├── ConsolidateStep.tsx          # Phase 6A→7: final consolidation
│   │       └── ExportStep.tsx               # Phase 7→8: generate output files
│   ├── App.tsx                # React Router setup
│   └── main.tsx               # Entry point + QueryClient
├── .env.example
├── package.json
├── tailwind.config.js
├── tsconfig.json
└── vite.config.ts
```

## Reconciliation Workflow & State Machine

The backend is a **forward-only state machine**. Each step advances the session to the next state.
No backward navigation is possible.

```
initialized
  └─ [Upload Files]  ──────────────────────────────→ files_loaded
       └─ [Run Profile]  ─────────────────────────→ profiled
            └─ [Run Preprocess]  ───────────────→ preprocessed
                 └─ [Run Deterministic]  ──────→ deterministic_complete
                      └─ [Confirm Det. Review] → deterministic_review_complete
                           └─ [Run Probabilistic] ─────────────→ probabilistic_complete
                                └─ [Probabilistic Review] ────→ probabilistic_review_complete
                                     └─ [Run AI] ────────────→ ai_suggested
                                          └─ [AI Review] ────→ ai_review_complete
                                               └─ [Consolidate] → final_consolidated
                                                    └─ [Export] ─→ finalized (terminal)
```

### Review phases

States `deterministic_complete`, `probabilistic_complete`, and `ai_suggested` are **review phases**.
During review phases the API blocks recomputation (returns 409). The UI enforces this by only
showing the review action CTA, not the computation CTA.

## Error Handling

| Status | Behavior |
|--------|----------|
| **409 Conflict** | Shown in amber warning box with "Refresh status" link. Usually means wrong pre-state or already-completed step. |
| **422 Validation** | Shown in red box with per-field location + message. Common for malformed CSV uploads. |
| Other errors | Shown in generic red error box. |

## Session Persistence

- `session_id` is stored in the URL path (`/sessions/:sessionId`) — refreshing the page keeps the session.
- A list of created session IDs is also stored in `localStorage` (`recon_sessions`) so the landing
  page can list previous sessions after a new browser tab.
- Match lists from the Probabilistic and AI steps are stored in `sessionStorage` to power the
  review UIs in the same session tab.

## Tech Stack

| Package | Use |
|---------|-----|
| Vite 5 | Build tool + dev server |
| React 18 | UI framework |
| TypeScript | Type safety |
| React Router 6 | Client-side routing |
| TanStack Query 5 | Server state / mutations / caching |
| Zod 3 | Runtime schema validation of API responses |
| Tailwind CSS 3 | Utility-first styling |
