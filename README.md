# Recon.AI

**AI-augmented financial reconciliation — built for the close, designed for the audit.**

---

## The Problem

Month-end reconciliation at scale is slow, manual, and error-prone. Finance teams spend days matching thousands of GL and subledger entries across vendors who appear under a dozen different names, amounts that shift by a rounding error, and dates that drift across cut-offs. The result: late closes, audit risk, and analysts buried in Excel.

Recon.AI replaces that workflow with a structured, human-governed process — AI does the heavy lifting on design, cleansing, matching, and explanation, while the human stays in control of every consequential decision.

---

## How It Works

Recon.AI guides a reconciliation from raw file upload to audit-ready export through a structured sequence of phases. AI is present throughout — not just at the matching step.

```
  Upload Files
       ↓
  AI-Recommended Data Cleansing
  Vendor normalization · deduplication · formatting standardization
  Human reviews and approves cleaning logic before it runs
       ↓
  Exploratory Data Analytics
  Profile your data: distributions, anomalies, coverage gaps
  AI generates a plain-English narrative summary of what it found
       ↓
  AI-Recommended Reconciliation Design
  AI analyzes your data and recommends matching rules and thresholds
  Human reviews, adjusts, and approves before any matching begins
       ↓
  Three-Gate Matching Engine (runs automatically)
  ┌──────────────────────────────────────────────────┐
  │  GATE 1 · Deterministic Matching                 │
  │  High-confidence rule-based matching.            │
  │               ↓ residuals                        │
  ├──────────────────────────────────────────────────┤
  │  GATE 2 · Probabilistic Matching                 │
  │  Weighted similarity scoring for fuzzier cases.  │
  │               ↓ residuals                        │
  ├──────────────────────────────────────────────────┤
  │  GATE 3 · AI Advisory Resolution                 │
  │  AI suggests matches for remaining residuals.    │
  └──────────────────────────────────────────────────┘
       ↓
  Single Consolidated Output
  All matches presented together with full reasoning.
  Human reviews, unmatches anything that looks wrong,
  and manually adds matches AI missed.
       ↓
  Final Consolidation & Export
  Audit-ready package: every decision, every step
```

---

## Human in the Loop — At the Right Moments

Recon.AI is designed around a simple principle: AI recommends, humans decide — but only where human judgment actually matters.

The three matching gates run automatically and produce a single consolidated result. The human's job is to review that result, not manage a multi-step approval process:

- **Before cleansing** — cleaning logic is shown and approved before any data is transformed
- **Before matching** — the reconciliation design (rules, thresholds, groupings) is presented for review and adjustment
- **After matching** — review the full consolidated match list; unmatch anything that looks wrong
- **Manual matching** — create matches directly for cases the engine missed
- **Full reasoning transparency** — every match shows the exact logic behind it, not just a confidence score

No data is mutated silently. Every action is logged.

---

## AI Narrative & Chatbot

Throughout the reconciliation, AI generates plain-English summaries of what it found, what it did, and why — written for finance professionals, not engineers. At any point, reviewers can ask follow-up questions via an AI chatbot that has full context of the session data, matches, and exceptions.

---

## Audit Exportability

Every step of the process is exportable:

| Export | Contents |
|---|---|
| Raw & cleaned data | Before/after for every cleansing transformation |
| Data profile | EDA summary, anomalies, coverage statistics |
| Matching logic | Rules applied, thresholds used, AI recommendations made |
| Match results | Accepted matches with full reasoning per record |
| Residuals & rejections | Unmatched records with status and reason |
| Override log | Every human unmatch and manual match with timestamp and rationale |
| Executive summary | PDF narrative of the full reconciliation |

The audit package is complete by design — an examiner can reconstruct every decision from the exported files without accessing the application.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · Uvicorn |
| Frontend | React · TypeScript · Vite · Tailwind CSS |
| AI/ML | OpenAI API · RapidFuzz (NLP similarity) |
| Infrastructure | Azure App Services · Azure Static Web Apps · Docker |
| CI/CD | GitHub Actions |
| Data | Pandas · Pydantic v2 |

---

## Status

**Proof of concept — actively developed.** The full reconciliation pipeline is implemented and tested end-to-end. Currently private; productionization (persistent storage, multi-tenancy, auth) is the next phase.

- 825 passing tests across 12 pipeline phases
- Full pipeline: upload → profile → preprocess → match → review → export
- Export outputs: matched results, residuals, rejections, override log, full audit trail (CSV + PDF)

---

## Screenshots

> *Coming soon — UI screenshots and a walkthrough video.*

---

## Built By

**Jared Carollo** — Managing Director, Analytics & Innovation · [LinkedIn](https://linkedin.com/in/jaredcarollo)

Built solo as a proof of concept for AI-augmented financial close automation.
