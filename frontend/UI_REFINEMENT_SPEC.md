# Admin Console Refinement Specification
AI Reconciliation Engine

## Purpose

Transform the current functional Admin console into a professional reconciliation workbench that enables:

- Full row-level inspection
- Step-by-step data lineage visibility
- Quantitative verification of matching performance
- Exportable audit artifacts
- Clear summary metrics (Big Ass Numbers format)

This console is for internal validation, debugging, optimization, and algorithm tuning.

API modifications are allowed where necessary to support visibility and analytics.

---

# GLOBAL PRINCIPLES

## 1. Full Transparency

Every step must show:

- Input dataset(s)
- Output dataset(s)
- Row counts in and out
- Dollar totals in and out
- Matching counts
- Residual counts
- Algorithmic decisions (where applicable)

The goal is full traceability.

---

## 2. Big Ass Numbers (BANS)

Every step page must begin with a BANS panel showing:

- Total Input Rows
- Total Output Rows
- Total Matched Rows
- Total Residual Rows
- Total Matched Dollars
- Total Residual Dollars
- Match Rate %
- Dollar Coverage %

BANS must be:
- Visually prominent
- Large typography
- Clean grid layout
- Green/red emphasis for performance

---

## 3. Row-Level Inspectability

For each step:

Display side-by-side:

LEFT:
Input table (before step)

RIGHT:
Output table (after step)

Tables must support:
- Sorting
- Filtering
- Sticky headers
- Column visibility toggle
- Search
- Pagination
- Confidence score visualization (if applicable)

The user must be able to inspect:
- The original values
- The transformation applied
- The match groupings
- The outcome of the step

---

## 4. Data Lineage Visibility

Every row in output must allow:

- Drill-down to source rows
- Visibility of grouping/match ID
- Confidence metrics
- Step-level reasoning (if AI or probabilistic)

---

## 5. Step Analytics Panel

Each step must include a structured analytics section showing:

- Matching summary by scenario_id
- Matching summary by grouping_type
- Residual breakdown
- Distribution of confidence scores
- Dollar-weighted match distribution
- Performance metrics

This may require API expansion.

---

## 6. Row Count Tracking

Every page must show:

- GL row count
- Subledger row count
- Chart of Accounts row count
- Rows entering this step
- Rows leaving this step
- Rows consumed by this step
- Rows remaining

These must be explicitly labeled.

---

## 7. Export System (Required on Every Page)

Each step must include an Export section with:

### Export Options:

Selectable checkboxes:
- Input data (raw)
- Output data
- Match tables
- Residual tables
- Step analytics summary
- Step metadata log
- System metadata

And:

[ Export Selected ]
[ Export All ]

Export format:
- CSV for data
- JSON for metadata
- Optional consolidated ZIP

System metadata must include:
- Session ID
- Timestamp
- Step name
- Version hash
- Matching configuration
- Execution duration

---

# API MODIFICATION GUIDELINES

API can be expanded to include:

- Full row datasets for each step
- Aggregated dollar totals
- Step-level analytics payload
- System metadata
- Execution time
- Row-level lineage mapping

Avoid:
- Breaking existing state machine
- Changing route names
- Removing existing fields

Add new structured response sections instead.

---

# PAGE STRUCTURE STANDARD

Every step page must follow this structure:

1. Step Header
2. BANS Panel
3. Row Count Summary
4. Input vs Output Table Comparison
5. Analytics Panel
6. Export Panel
7. Step Metadata Panel (collapsible)

Consistency across all step pages is mandatory.

---

# VISUAL DESIGN GOALS

- Enterprise SaaS aesthetic
- Clean grid layout
- Clear hierarchy
- Generous spacing
- Muted base palette
- Strong primary accent
- Green for matched
- Red for residual
- No visual clutter
- No raw JSON visible by default (collapsible only)

---

# PERFORMANCE REQUIREMENTS

Tables must:

- Handle large datasets gracefully
- Support pagination
- Avoid freezing UI
- Avoid rendering entire dataset at once if > 1,000 rows

---

# PRIORITIZATION ORDER

1. Deterministic Step
2. Probabilistic Step
3. AI Step
4. Consolidation Step
5. Profile Step
6. Preprocess Step
7. Upload Step
8. Export Step
9. Dashboard

Refine in this order.

---

# CONSTRAINTS

- Do not modify state machine sequencing.
- Do not remove existing functionality.
- Do not introduce new heavy UI libraries without approval.
- Prefer extending current architecture.
- Preserve TypeScript typing discipline.

---

# DEFINITION OF DONE

The Admin console should feel like:

- A financial audit workbench
- A data science validation environment
- A reconciliation debugging cockpit

The user must be able to confidently answer:

- What happened at this step?
- How many rows moved?
- How many dollars moved?
- Why did this match?
- What remains unmatched?
- Can I export everything for audit?

If any of these are unclear, the page is incomplete.