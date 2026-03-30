import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronUp } from 'lucide-react'

interface FAQItem {
  q: string
  a: string | React.ReactNode
}

const FAQ_SECTIONS: { heading: string; items: FAQItem[] }[] = [
  {
    heading: 'Getting Started',
    items: [
      {
        q: 'What files do I need to run a reconciliation?',
        a: 'You need two CSV files: a General Ledger (GL) export and a Subledger export. The files must share at least a vendor/payee column, an amount column, and a date column. An ID column on each side (e.g. GL0001, SUB0001) is strongly recommended for traceability. An optional Chart of Accounts (CoA) file can be uploaded to enrich analysis.',
      },
      {
        q: 'What column names are required?',
        a: (
          <>
            <p className="mb-2">
              The engine is flexible about column names. During the <em>Load &amp; Clean</em> step, an AI
              column-mapping step analyzes your column headers and sample data, then suggests the semantic
              role for each column (ID, Vendor, Amount, Date, Entity, Currency). You review and confirm
              these mappings before matching begins.
            </p>
            <p>
              If you skip the mapping step, the engine falls back to default column name expectations:
              <code className="bg-[#f0f0f0] px-1 rounded text-xs mx-1">vendor_name</code>,
              <code className="bg-[#f0f0f0] px-1 rounded text-xs mx-1">amount</code>,
              <code className="bg-[#f0f0f0] px-1 rounded text-xs mx-1">transaction_date</code>,
              <code className="bg-[#f0f0f0] px-1 rounded text-xs mx-1">entity</code>, and an ID column on each side.
            </p>
          </>
        ),
      },
      {
        q: 'How large can my files be?',
        a: 'The engine is tested on files with tens of thousands of rows. The probabilistic and AI stages scale linearly, so very large files (hundreds of thousands of rows) may take longer. The chat assistant sends up to 500 rows per side to the AI model for context; matching itself processes all rows regardless of file size.',
      },
      {
        q: 'What does "session" mean?',
        a: 'A session is a single reconciliation run. Each session gets a unique ID, stores your uploaded files, tracks pipeline state, and accumulates all intermediate results and snapshots. Sessions are in-memory and are not persisted across server restarts in the current MVP. The "Restart" button in the sidebar clears the current session ID and starts a new one.',
      },
    ],
  },
  {
    heading: 'The Matching Pipeline',
    items: [
      {
        q: 'Why does the engine use three matching stages instead of one?',
        a: 'Different transactions require different matching strategies. A deterministic exact match is the most trustworthy and should be used wherever possible. Probabilistic scoring catches near-matches that deterministic rules would miss. AI reasoning handles the long tail of edge cases that neither rule-based nor numeric approaches can address. Processing stages in order from highest to lowest confidence ensures that each matched record has the strongest possible justification.',
      },
      {
        q: 'What is the residual pool?',
        a: 'After each matching stage, the rows that were not matched become the residual pool and are passed to the next stage. A GL row in the residual pool after all three stages appears in the "Unmatched GL" section of the export. The same applies to Subledger rows.',
      },
      {
        q: 'Can a record be matched by more than one stage?',
        a: 'No. Once a record is matched by any stage, it is removed from the residual pool and cannot be matched again. This prevents double-counting.',
      },
      {
        q: 'What does confidence score mean?',
        a: (
          <>
            <p className="mb-2">Confidence score indicates how certain the engine is that two records are a true match:</p>
            <ul className="space-y-1 text-sm">
              <li><strong>100% (Deterministic S1):</strong> Exact match on all fields — vendor, amount, date, entity.</li>
              <li><strong>95% (Deterministic S2):</strong> All fields match with a date tolerance of 30 days.</li>
              <li><strong>90% (Deterministic S3):</strong> All fields match with a date tolerance of 60 days.</li>
              <li><strong>Probabilistic:</strong> A weighted similarity score (default 85%+ threshold). Each row's tooltip shows the component breakdown (vendor, amount, date similarities and their weights).</li>
              <li><strong>AI:</strong> The model's self-reported confidence, accompanied by a plain-English reasoning narrative.</li>
            </ul>
          </>
        ),
      },
      {
        q: 'What is vendor normalization and why does it matter?',
        a: 'Vendor names are often stored inconsistently across GL and Subledger systems (e.g. "Acme Corp.", "ACME CORPORATION", "Acme Co"). Before matching, the engine normalizes all vendor names through a three-tier cascade: rule-based string cleaning (lowercase, punctuation removal, suffix stripping), NLP fuzzy matching (rapidfuzz, 90% threshold), and AI-assisted resolution. This ensures that structurally equivalent vendor names resolve to the same canonical key for join operations.',
      },
    ],
  },
  {
    heading: 'Probabilistic Matching',
    items: [
      {
        q: 'How are the similarity weights determined?',
        a: (
          <>
            <p className="mb-2">
              Default weights (vendor 45%, amount 40%, date 15%) reflect the relative importance of
              each field in a typical financial reconciliation: vendor identity is the strongest signal,
              amount equality is nearly as important, and date proximity is a supporting signal but
              less discriminating.
            </p>
            <p>
              These weights are configurable via the matching configuration step. You can also adjust
              the acceptance threshold (default 85%) and the date and amount tolerance windows.
            </p>
          </>
        ),
      },
      {
        q: 'What is the acceptance threshold?',
        a: 'The acceptance threshold (default 85%) is the minimum final similarity score required for a probabilistic match to be surfaced for review. Records with a score below the threshold are not shown as potential matches and go directly to the residual pool. Raising the threshold produces fewer, higher-confidence suggestions; lowering it surfaces more potential matches at lower confidence.',
      },
      {
        q: 'What does "N:1" or "1:N" matching mean?',
        a: 'Some transactions are legitimately split across multiple records on one side. For example, a single Subledger entry for $1,000 might correspond to two GL entries of $600 and $400. N:1 matching groups multiple GL rows and scores them against a single Subledger row. 1:N works in reverse. Both cardinalities are handled in the probabilistic stage.',
      },
    ],
  },
  {
    heading: 'Review and Override',
    items: [
      {
        q: 'What happens when I reject a probabilistic or AI match?',
        a: 'Rejected matches are removed from the accepted match list and both records are returned to the residual pool. They will appear in the unmatched export unless you manually override them with a different match using the override tool in the Unmatched Analysis page.',
      },
      {
        q: 'How do I manually override a match?',
        a: (
          <>
            <p>
              On the <em>Unmatched Analysis</em> page, each unmatched section (GL and Subledger) has an
              override input. Enter one or more GL IDs (e.g. <code className="bg-[#f0f0f0] px-1 rounded text-xs">GL0001, GL0055</code>) and
              their corresponding Subledger IDs (e.g. <code className="bg-[#f0f0f0] px-1 rounded text-xs">SUB0012</code>) and submit. The override is
              flagged in the final export as a manual override for audit purposes.
            </p>
          </>
        ),
      },
      {
        q: 'Are my review decisions saved?',
        a: 'Yes. All accept/reject decisions and manual overrides are stored in the session runtime and included in the final export. The export package contains a full audit trail showing which records were matched by each stage, which were reviewed and by whom, and which were manually overridden.',
      },
      {
        q: 'Can I go back and change a decision I already made?',
        a: 'The pipeline uses forward-only state transitions. Once you advance past a review step, the decisions from that step are locked and feed into the next stage. If you need to redo a review, you can restart the session and re-upload your files.',
      },
    ],
  },
  {
    heading: 'AI and the Chat Assistant',
    items: [
      {
        q: 'Is the AI matching result final?',
        a: 'No. AI matching is always advisory. The engine will never automatically accept an AI-suggested match. Every AI suggestion must be reviewed and explicitly accepted by a human user before it enters the final reconciliation. This is by design to ensure auditability.',
      },
      {
        q: 'What can I ask the chat assistant?',
        a: 'The chat assistant has access to your session context — the state of the pipeline, your column mapping, file statistics, and the actual transaction data (up to 500 rows per side). You can ask questions like "Which vendor has the most unmatched GL transactions?", "Why might these two records not be matching?", "What does the entity column contain?", or "Summarize the match results so far."',
      },
      {
        q: 'Does the AI see my raw transaction data?',
        a: 'Within a session, the chat assistant includes up to 500 rows per side of the actual transaction data in its context. This data is sent to the AI API per-request and is not stored or retained by the AI provider beyond the API call. No raw data is written to any external database. For very sensitive data, consult your organization\'s data governance policy before uploading.',
      },
      {
        q: 'What AI model is used?',
        a: 'The default model is OpenAI gpt-4o-mini, which provides a strong balance of reasoning quality and response speed for financial data analysis. The model is configurable per session in the session config if a different model is preferred.',
      },
    ],
  },
  {
    heading: 'Export and Output',
    items: [
      {
        q: 'What files are included in the export package?',
        a: (
          <ul className="space-y-1.5 text-sm">
            {[
              ['matched_gl.csv', 'All matched GL records with match IDs, stage, and confidence scores.'],
              ['matched_subledger.csv', 'All matched Subledger records with matching metadata.'],
              ['unmatched_gl.csv', 'GL records with no match after all three stages.'],
              ['unmatched_subledger.csv', 'Subledger records with no match after all three stages.'],
              ['match_summary.csv', 'Consolidated summary: match counts and amounts by stage.'],
              ['executive_summary.pdf', 'Optional PDF with narrative, pipeline statistics, and charts (requires PDF export option).'],
            ].map(([file, desc]) => (
              <li key={file} className="flex gap-2">
                <code className="bg-[#f0f0f0] px-1.5 py-0.5 rounded text-xs text-[#333] shrink-0 font-mono">{file}</code>
                <span>{desc}</span>
              </li>
            ))}
          </ul>
        ),
      },
      {
        q: 'Is the export audit-ready?',
        a: 'Yes. The export package includes full traceability: every matched record carries a match ID, the matching stage (deterministic/probabilistic/AI), the confidence score, and an override flag if applicable. AI match records also include the model\'s reasoning narrative. The package is designed to be provided directly to auditors or used in management reporting.',
      },
      {
        q: 'Can I export partial results?',
        a: 'The Export page becomes available after the final consolidation step. It produces the complete export package for the full reconciliation run. Partial exports of individual stages are not currently supported.',
      },
    ],
  },
]

function FAQAccordionItem({ item }: { item: FAQItem }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-[#e0e0e0] last:border-b-0">
      <button
        type="button"
        className="w-full flex items-start justify-between gap-4 py-4 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="text-sm font-semibold text-[#1a1a1a] leading-snug">{item.q}</span>
        {open
          ? <ChevronUp className="size-4 text-[#98002E] shrink-0 mt-0.5" />
          : <ChevronDown className="size-4 text-[#555] shrink-0 mt-0.5" />}
      </button>
      {open && (
        <div className="pb-4 text-sm text-[#444] leading-relaxed">
          {item.a}
        </div>
      )}
    </div>
  )
}

export function FAQ() {
  return (
    <div className="max-w-3xl mx-auto py-8 px-2">
      {/* Page header */}
      <div className="mb-10">
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-2">Frequently Asked Questions</h1>
        <p className="text-[#555] text-base">
          Common questions about how the reconciliation pipeline works and how to get the most out of it.
        </p>
      </div>

      <div className="space-y-8">
        {FAQ_SECTIONS.map(({ heading, items }) => (
          <section key={heading}>
            <h2 className="text-base font-semibold uppercase tracking-wider text-[#98002E] mb-1 pb-2 border-b border-[#d1d1d1]">
              {heading}
            </h2>
            <div className="bg-white rounded-xl border border-[#e0e0e0] shadow-sm px-5">
              {items.map((item) => (
                <FAQAccordionItem key={item.q} item={item} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Footer nav */}
      <div className="border-t border-[#d1d1d1] mt-10 pt-6 flex justify-between items-center text-sm text-[#888]">
        <Link to="/documentation" className="text-[#98002E] hover:text-[#6b0022] font-medium transition-colors">
          ← Documentation
        </Link>
        <Link to="/load-files" className="text-[#98002E] hover:text-[#6b0022] font-medium transition-colors">
          Get Started →
        </Link>
      </div>
    </div>
  )
}
