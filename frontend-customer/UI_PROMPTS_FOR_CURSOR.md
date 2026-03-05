# ReconAI UI Build Prompts (Cursor)

These prompts are used sequentially to build the UI quickly using Cursor.

---

# Prompt 1 — App Shell

Create a modern SaaS dashboard layout using React, Tailwind, and shadcn/ui.

Requirements:

Left sidebar navigation containing:

- Load Files
- Matching
- High-Level Analysis
- Detailed Analysis & Export

Main content panel on the right.

Style guidelines:

- modern fintech aesthetic
- generous whitespace
- rounded cards
- accent color for active navigation

Use Tailwind and shadcn components.

---

# Prompt 2 — Landing Page

Build a landing page component for ReconAI.

Content:

Title: ReconAI

Subtitle:
"Reconcile your GL in minutes with audit-ready outputs."

Supporting text:
"Built for busy accounting professionals."

Primary button:
Get Started

Button navigates to the Load Files page.

Style:

modern fintech hero
large typography
clean layout
accent highlight

---

# Prompt 3 — File Upload UI

Build a drag-and-drop upload interface.

Two upload zones:

GL File  
Subledger File

Accepted types:

CSV
XLSX

After upload show:

- row count
- date range
- vendor count
- total dollars
- duplicate records
- missing values

Use card layout.

---

# Prompt 4 — Column Histogram Hover

Add histogram previews for dataset columns.

Requirements:

Column names are displayed in a table.

When hovering a column name, display a small histogram tooltip showing distribution.

Use a lightweight chart component.

Avoid clutter — histograms should not appear unless hovered.

---

# Prompt 5 — Vendor Preprocessing Preview

Build a vendor normalization preview component.

Display a table:

Original Vendor | Normalized Vendor

Allow user override of normalized value before matching.

Include confirmation button:

"Accept Vendor Normalization"

---

# Prompt 6 — Matching Pipeline Page

Build a pipeline progress UI.

Display phases:

Deterministic Matching  
Probabilistic Matching  
AI Matching

Each phase should display:

- status (queued / running / complete)
- records processed

Include cancel button.

Show progress visually.

---

# Prompt 7 — High Level Analysis Page

Build a dashboard with:

Top metrics (BANS):

- Match Rate
- Matched $
- Unmatched $

Below that show a funnel chart:

Total Records  
Deterministic  
Probabilistic  
AI  
Unmatched

Include an AI narrative panel showing a generated summary.

---

# Prompt 8 — Review Table

Build a reviewable reconciliation table.

Grouped headers:

GENERAL LEDGER:
Entity | Vendor | Date | Amount

SUBLEDGER:
Entity | Vendor | Date | Amount

MATCH INFO:
Method | Confidence

Rows must be expandable.

Expanded row displays:

- full GL record
- full Subledger record
- match metadata

Actions inside expanded panel:

Accept Match  
Override Match  
Mark Unmatched

---

# Prompt 9 — Filters

Add filters above the review table:

Confidence Score  
Dollar Amount  
Match Phase  
Date Range

Filters should update table results dynamically.

---

# Prompt 10 — Detailed Analysis Page

Build unmatched transaction analysis page.

Include:

table of unmatched records

analytics cards showing:

- top unmatched vendors
- largest unmatched transactions

---

# Prompt 11 — Export Builder

Build export selection UI.

User can select:

- upload dataset
- preprocessing output
- deterministic output
- probabilistic output
- AI output
- final results after overrides
- unmatched dataset
- processing log
- executive summary PDF

Export generates a single downloadable ZIP.

---

# Prompt 12 — UI Polish

Improve the UI to feel like a modern fintech analytics product.

Enhancements:

- subtle hover states
- smooth expand animations
- consistent spacing
- improved typography hierarchy
- accent color usage

Reference style similar to Stripe, Linear, or Vercel dashboards.