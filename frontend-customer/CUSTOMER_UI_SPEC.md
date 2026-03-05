IMPORTANT:
Follow the existing repository structure when creating files.
The architecture examples below are guidelines, not mandatory paths.
Do not refactor existing folders unless necessary.
First inspect the repository structure before generating code.
Align all new files with the existing project structure.

# ReconAI Customer UI Spec (V1)
Owner: Jared  
Audience: Accounting Manager  
Design: Modern FinTech, professional yet approachable  
Primary Brand: ReconAI  
Theme: Accent color (single primary accent used consistently)

---

## 0) Goal
Build a customer-facing UI for ReconAI that:
- feels premium (not generic)
- supports a tight build/iterate loop (hot reload)
- provides clear 5-page flow
- enables row-level review + overrides for deterministic/probabilistic/AI matches
- produces an audit-ready export ZIP including step-level datasets + executive summary PDF

---

## 1) Tooling + Stack (Recommended)
### Framework
- React + TypeScript
- Prefer: Vite (fast HMR) or Next.js (if already in use). Choose whatever aligns with current repo.
- Routing: React Router (if Vite) OR Next.js App Router (if Next).

### UI + Styling
- TailwindCSS
- shadcn/ui components
- Typography: Inter or Geist
- Icons: lucide-react

### Data + State
- TanStack Query (React Query) for API calls + polling job status
- Zustand (optional) for lightweight shared UI state (upload session, selections)

### Tables + Charts
- TanStack Table for data grids
- Recharts or lightweight chart lib for funnel/bars (keep charts minimal and readable)

### File Upload + Export
- Upload: native input + drag/drop (react-dropzone optional)
- Export download: API returns ZIP (application/zip)

---

## 2) Global UX Principles
1) Always show “where I am” in the flow (left nav + page title).
2) Default to “scan first, details on demand” (expand rows for full detail).
3) Avoid clutter: show essentials, hide deeper detail behind hover/expand/drawer.
4) Make the pipeline feel sophisticated: progress indicators, clear statuses, counts.
5) Everything should feel audit-ready: explicit logs, override trail, export bundle.

---

## 3) Information Architecture
### 5 Pages
1) Landing
2) Load Files
3) Matching
4) High-Level Analysis
5) Detailed Analysis & Export

### Navigation (Left Sidebar)
- Landing (optional in nav after start)
- Load Files
- Matching
- High-Level Analysis
- Detailed Analysis & Export

Keep nav locked to a single session (V1). No multi-job history needed.

---

## 4) Page Specs (Locked)

### Page 1: Landing
**Hero**
- Title: ReconAI
- Subtitle: “Reconcile your GL in minutes with audit-ready outputs.”
- Supporting: “Built for busy accounting professionals.”
- CTA: “Get Started” → Page 2 (Load Files)
- Style: modern fintech hero with strong typography and accent highlight

**Process Overview**
- Brief explanation:
  - Starts with strongest signal then expands to broader criteria
  - Deterministic → Probabilistic → AI
  - User can do row-level review + override
  - Output is an audit-ready export package

---

### Page 2: Load Files
**Required uploads**
- GL file (CSV/XLSX)
- Subledger file (CSV/XLSX)

**Column mapping**
- Desired: flexible column mapping
- V1 decision rule:
  - If simple: implement mapping UI
  - If complex: assume standard column names, defer to V2

**Vendor preprocessing**
- Runs automatically after upload
- Show before/after preview
- Allow user override before matching

**Data profiling stats (immediate)**
- row count
- date range
- vendor count
- total dollars
- duplicates
- missing values

**Histograms**
- For all columns
- Not visible by default
- Appear on hover over column name (tooltip/panel)

**Error handling**
- If upload fails: show warning “Upload failed due to data input error.”
- No detailed row diagnostics required (V1)

**Primary CTA**
- “Run Matching” → Page 3

---

### Page 3: Matching
**Behavior**
- Clicking “Run Matching” executes deterministic → probabilistic → AI automatically.
- No phase toggles (V1)
- No early exit logic (always run all phases)

**Progress UI**
- Show live status per phase (queued/running/done/error)
- Show “records processed” per phase
- Provide Cancel button:
  - Cancel stops the run and returns user to Load Files

**Results**
- Do not show deep analysis here
- On completion, CTA: “View Results” → Page 4

---

### Page 4: High-Level Analysis
**BANS**
- Match Rate %
- Matched $
- Unmatched $

**Funnel**
- Simple funnel visualization:
  - Total Records → Deterministic → Probabilistic → AI → Unmatched

**AI Narrative**
Executive summary style text panel containing:
1) brief description of processing/matching approach
2) brief description of outcome
3) suggestions on where to start reviewing overrides
4) recurring transaction patterns

**Reviewable records**
- Deterministic, Probabilistic, AI matches are ALL reviewable and overridable
- Unmatched records do NOT appear here (they appear on Page 5)

**Review table layout**
Grouped headers:

GENERAL LEDGER:
- Entity | Vendor | Date | Amount

SUBLEDGER:
- Entity | Vendor | Date | Amount

MATCH INFO:
- Method | Confidence | Review

Row expansion (collapsible panel):
- Show ALL columns for GL + Subledger
- Show match metadata: phase/method, confidence, signals used
- Provide actions:
  - Accept Match
  - Override Match
  - Mark Unmatched

**Filters**
- Confidence score
- Dollar amount
- Phase/Method
- Date range

**Audit trail**
Overrides store:
- original match
- user override
- timestamp

---

### Page 5: Detailed Analysis & Export
**Unmatched analysis**
- Table of unmatched records
- Analytics summary:
  - top unmatched vendors
  - largest unmatched transactions
  - concentration patterns

**Exports**
User selects artifacts → download as one ZIP containing only selected items.

Selectable datasets:
- Data at upload (raw)
- Preprocessing output
- Deterministic input/output
- Probabilistic input/output
- AI input/output
- Final dataset after overrides
- Residual unmatched dataset
- Processing log

**Executive summary PDF**
Included in ZIP if selected.
Content:
- overview of reconciliation
- summary statistics
- funnel visualization
- key findings
- recurring transaction patterns
Style: executive summary narrative

---

## 5) Backend Contract Assumptions (UI Needs)
> If any of these endpoints don’t exist, create/adjust backend as needed.

### Session Model (V1)
- Single active session per user/browser
- Backend returns a `job_id` for matching runs

### Required Endpoints (suggested)
1) Upload
- `POST /upload/gl`
- `POST /upload/subledger`

2) Profiling
- `GET /profile` returns:
  - counts, date ranges, vendor counts, totals, dupes, missing
  - per-column histogram data (or request per-column on hover)

3) Vendor preprocessing
- `POST /preprocess/vendors`
- `GET /preprocess/vendors/preview`
- `POST /preprocess/vendors/overrides` (optional)

4) Matching jobs
- `POST /jobs/match` → `{ job_id }`
- `GET /jobs/{job_id}` → status, phase, progress, counts processed per phase
- `POST /jobs/{job_id}/cancel`

5) Results
- `GET /results/summary` → BANS, funnel counts, distributions
- `GET /results/matches?filters...&page...`
- `GET /results/matches/{match_id}` → full GL+SL row detail + metadata
- `POST /results/matches/{match_id}/override` → stores original + override + timestamp

6) Unmatched
- `GET /results/unmatched?filters...&page...`
- `GET /results/unmatched/summary` → top vendors, largest, concentration

7) Narrative + PDF
- `GET /results/narrative` → text narrative for Page 4
- `POST /export` with selected artifacts → returns ZIP
  - ZIP may include executive summary PDF if selected

8) Logs
- `GET /logs` or included in export artifact

---

## 6) Frontend Architecture (Implementation)
### Suggested Folder Structure
If Vite + React Router:

frontend/
  src/
    app/
      routes/
        Landing.tsx
        LoadFiles.tsx
        Matching.tsx
        HighLevelAnalysis.tsx
        DetailedAnalysisExport.tsx
      AppShell.tsx
      router.tsx
    components/
      layout/
        Sidebar.tsx
        PageHeader.tsx
      upload/
        FileDropzone.tsx
        UploadStatusCard.tsx
        ColumnHistogramHover.tsx
        VendorPreprocessPreview.tsx
      pipeline/
        PipelineProgress.tsx
        PhaseStatusRow.tsx
        CancelRunButton.tsx
      analysis/
        BANS.tsx
        Funnel.tsx
        NarrativePanel.tsx
        MatchesReviewTable.tsx
        MatchRowExpandedPanel.tsx
        FiltersBar.tsx
      detailed/
        UnmatchedTable.tsx
        UnmatchedSummaryCards.tsx
        ExportBuilder.tsx
        ExportSelectionList.tsx
    api/
      client.ts
      endpoints.ts
      hooks/
        useUpload.ts
        useProfile.ts
        usePreprocess.ts
        useMatchJob.ts
        useResults.ts
        useExport.ts
    state/
      sessionStore.ts (optional Zustand)
    styles/
      globals.css
    utils/
      formatters.ts
      download.ts

If Next.js, map these into app/ routes + components similarly.

---

## 7) Key UI Components (Build Order)
1) AppShell layout (sidebar + content)
2) Landing page (hero + CTA)
3) LoadFiles upload experience (GL + Subledger)
4) Profiling cards + hover histograms
5) Vendor preprocess preview + overrides
6) Matching pipeline progress + cancel
7) High-level analysis: BANS + funnel + narrative
8) Review table + filters + expandable row + override actions
9) Detailed analysis: unmatched table + analytics
10) Export builder + ZIP download + executive summary PDF selection

---

## 8) Style Recommendations (Make It “Pop”)
### Layout
- Use card-based sections with consistent padding and spacing
  - `rounded-2xl`, `shadow-sm`, `p-6`, `gap-6`
- Keep generous whitespace; avoid dense layouts

### Typography hierarchy
- Page title: large + bold
- BANS: very large numerals
- Supporting text: muted, smaller

### Accent Color Use (Rules)
- Use accent for:
  - primary buttons
  - active nav item
  - key highlights (match rate, important chips)
- Avoid rainbow UI; keep it restrained and premium

### Interaction polish
- Subtle hover states on cards + rows
- Smooth expand/collapse transitions
- Loading states:
  - skeletons for tables
  - progress indicators for pipeline

### Tables
- Dense enough for accounting users but not cramped
- Sticky header + pagination
- Expand row for full detail

---

## 9) Performance / UX Requirements
- Hot reload workflow must be fast locally
- Tables must support pagination (no rendering 10k rows)
- Poll job status on Matching page (e.g., every 1–2 seconds while running)
- All long-running operations show a clear loading/progress state

---

## 10) V1 Explicit Non-Goals (Defer)
- Multi-job history / job library
- User auth, billing, org management
- Detailed upload error diagnostics
- Advanced column mapping if it materially complicates V1

---

## 11) Acceptance Checklist (V1)
- 5-page flow is complete and navigable
- Upload supports CSV/XLSX for GL + Subledger
- Vendor preprocessing preview + override works
- Matching run shows phase-by-phase progress, records processed, and supports cancel
- High-level analysis shows BANS + funnel + AI narrative
- Review table shows GL + Subledger grouped headers and expandable row detail
- Overrides work for deterministic/probabilistic/AI matches and create audit trail
- Detailed analysis includes unmatched + analytics summary
- Export produces ZIP including selected artifacts + optional executive summary PDF