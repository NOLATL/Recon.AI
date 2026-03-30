import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mb-12">
      <h2 className="text-2xl font-bold text-[#98002E] mb-5 pb-2 border-b border-[#d1d1d1]">{title}</h2>
      {children}
    </section>
  )
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className="text-lg font-semibold text-[#1a1a1a] mb-2">{title}</h3>
      {children}
    </div>
  )
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white rounded-xl border border-[#e0e0e0] p-5 shadow-sm ${className}`}>
      {children}
    </div>
  )
}

function MathBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-[#f5f5f5] border border-[#d1d1d1] rounded-lg p-4 font-mono text-sm text-[#333333] mt-2 mb-3 overflow-x-auto">
      {children}
    </div>
  )
}

export function Documentation() {
  return (
    <div className="max-w-4xl mx-auto py-8 px-2">
      {/* Page header */}
      <div className="mb-10">
        <h1 className="text-3xl font-bold text-[#1a1a1a] mb-2">Documentation</h1>
        <p className="text-[#555] text-base">
          A complete technical reference for the Recon.AI reconciliation pipeline.
        </p>
      </div>

      {/* In-page navigation */}
      <nav className="bg-white rounded-xl border border-[#e0e0e0] p-4 mb-10 shadow-sm">
        <p className="text-xs font-semibold text-[#888] uppercase tracking-wider mb-3">On this page</p>
        <div className="flex flex-col gap-1.5">
          {[
            ['#executive-summary', 'Executive Summary'],
            ['#waterfall', 'Three-Stage Matching Waterfall'],
            ['#ai-usage', 'How AI Is Used'],
          ].map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="flex items-center gap-1.5 text-sm text-[#98002E] hover:text-[#6b0022] transition-colors"
            >
              <ChevronRight className="size-3.5 shrink-0" />
              {label}
            </a>
          ))}
        </div>
      </nav>

      {/* ── 1. Executive Summary ── */}
      <Section id="executive-summary" title="Executive Summary">
        <p className="text-[#333] leading-relaxed mb-4">
          Recon.AI automates the reconciliation of two financial data sets — typically a General Ledger
          (GL) and a Subledger — and produces a complete, audit-ready output package. The engine is
          designed for accounting and finance professionals who need fast, defensible reconciliations
          without manual row-by-row comparison.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {[
            {
              label: 'Purpose',
              text: 'Identify which transactions across two financial files match, which are unmatched, and why—with full traceability and confidence scoring at every step.',
            },
            {
              label: 'Process',
              text: 'A three-stage waterfall (deterministic → probabilistic → AI) processes each record in order from highest to lowest confidence, with unmatched rows cascading to the next stage.',
            },
            {
              label: 'Outcome',
              text: 'A finalized match list, unmatched residual analysis, override audit trail, and an exportable package (CSVs + optional executive PDF) ready for auditors or management reporting.',
            },
          ].map(({ label, text }) => (
            <Card key={label}>
              <p className="text-xs font-semibold uppercase tracking-wider text-[#98002E] mb-2">{label}</p>
              <p className="text-sm text-[#444] leading-relaxed">{text}</p>
            </Card>
          ))}
        </div>

        <Card>
          <p className="text-sm font-semibold text-[#1a1a1a] mb-2">End-to-end pipeline</p>
          <div className="flex flex-wrap items-center gap-1.5 text-sm text-[#555]">
            {[
              'Load & Validate',
              'Profile',
              'Preprocess & Normalize',
              'Deterministic Match',
              'Probabilistic Match',
              'AI Match',
              'Review & Override',
              'Consolidate',
              'Export',
            ].map((step, i, arr) => (
              <span key={step} className="flex items-center gap-1.5">
                <span className="bg-[#f0e6ea] text-[#98002E] px-2 py-0.5 rounded-full text-xs font-medium">{step}</span>
                {i < arr.length - 1 && <ChevronRight className="size-3 text-[#aaa]" />}
              </span>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── 2. Three-Stage Waterfall ── */}
      <Section id="waterfall" title="Three-Stage Matching Waterfall">
        <p className="text-[#333] leading-relaxed mb-6">
          The engine processes every transaction through three matching stages in strict order.
          Each stage claims the records it can match with the required confidence, and the
          remaining unmatched records (the <em>residual pool</em>) are passed to the next stage.
          No record can be matched by more than one stage.
        </p>

        {/* Stage 1 */}
        <Card className="mb-5 border-l-4 border-l-[#16a34a]">
          <div className="flex items-start gap-3 mb-3">
            <span className="bg-[#16a34a] text-white text-xs font-bold px-2.5 py-0.5 rounded-full shrink-0 mt-0.5">Stage 1</span>
            <h3 className="text-base font-semibold text-[#1a1a1a]">Deterministic Matching</h3>
          </div>

          <SubSection title="Purpose">
            <p className="text-sm text-[#444] leading-relaxed">
              Deterministic matching applies exact, rule-based criteria to find the highest-confidence
              matches first. Because the rules are precise and leave no ambiguity, every match produced
              here carries full confidence and requires no human judgment to accept.
            </p>
          </SubSection>

          <SubSection title="Matching Scenarios (ordered by strictness)">
            <div className="space-y-2 text-sm text-[#444]">
              {[
                { id: 'S1', conf: '100%', rule: 'Vendor + Amount + Date (exact) + Entity' },
                { id: 'S2', conf: '95%', rule: 'Vendor + Amount + Entity + Date within 30 days' },
                { id: 'S3', conf: '90%', rule: 'Vendor + Amount + Entity + Date within 60 days' },
              ].map(({ id, conf, rule }) => (
                <div key={id} className="flex items-start gap-3 bg-[#f9fafb] rounded-lg px-3 py-2">
                  <span className="font-mono font-semibold text-[#16a34a] w-5 shrink-0">{id}</span>
                  <span className="font-semibold text-[#1a1a1a] w-12 shrink-0">{conf}</span>
                  <span>{rule}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-[#888] mt-2">
              Each scenario only processes records not already consumed by an earlier scenario.
              Amount comparison is rounded to 2 decimal places to avoid floating-point drift.
            </p>
          </SubSection>

          <SubSection title="Math">
            <MathBox>
              {`Exact match:   round(gl.amount, 2) == round(sub.amount, 2)
                             AND normalize(gl.vendor) == normalize(sub.vendor)
                             AND gl.entity == sub.entity
                             AND abs(gl.date - sub.date) <= tolerance_days`}
            </MathBox>
            <p className="text-sm text-[#444]">
              Vendor normalization is applied before comparison (see <em>Preprocessing</em> below).
              Entity matching uses exact equality; date tolerances are 0 days (S1), 30 days (S2), 60 days (S3).
            </p>
          </SubSection>

          <SubSection title="Residuals">
            <p className="text-sm text-[#444]">
              Any GL or Subledger row not consumed by all three scenarios is added to the residual
              pool and forwarded to Stage 2.
            </p>
          </SubSection>

          <SubSection title="Dynamic configuration">
            <p className="text-sm text-[#444]">
              The scenario definitions (match fields, tolerances, confidence scores) are stored in
              the session's <code className="bg-[#f0f0f0] px-1 rounded text-xs">matching_config</code> at
              runtime. A matching configuration chat step lets you review AI-suggested scenarios and
              adjust tolerances before running. If no custom config is confirmed, the three default
              scenarios above apply.
            </p>
          </SubSection>
        </Card>

        {/* Stage 2 */}
        <Card className="mb-5 border-l-4 border-l-[#2563eb]">
          <div className="flex items-start gap-3 mb-3">
            <span className="bg-[#2563eb] text-white text-xs font-bold px-2.5 py-0.5 rounded-full shrink-0 mt-0.5">Stage 2</span>
            <h3 className="text-base font-semibold text-[#1a1a1a]">Probabilistic Matching</h3>
          </div>

          <SubSection title="Purpose">
            <p className="text-sm text-[#444] leading-relaxed">
              Probabilistic matching handles near-matches and partial overlaps that deterministic
              rules would miss — vendor name typos, slight date discrepancies, rounding differences.
              Every match is scored on a 0–100% similarity scale; only scores above the configured
              threshold are accepted.
            </p>
          </SubSection>

          <SubSection title="Similarity scoring">
            <MathBox>
              {`final_score = (vendor_sim × w_vendor)
             + (amount_sim × w_amount)
             + (date_sim   × w_date)

Default weights:  w_vendor = 0.45,  w_amount = 0.40,  w_date = 0.15
Default threshold: 0.85  (85% similarity required to accept)`}
            </MathBox>
            <div className="space-y-1 text-sm text-[#444]">
              <p><strong>vendor_sim</strong> — token-sort fuzzy ratio (rapidfuzz) between normalized vendor names, 0–1.</p>
              <p><strong>amount_sim</strong> — 1 if amounts match exactly, decays linearly with percentage difference.</p>
              <p><strong>date_sim</strong> — 1 if same date, decays linearly to 0 at the configured date tolerance window.</p>
            </div>
          </SubSection>

          <SubSection title="Match cardinalities">
            <div className="grid grid-cols-3 gap-3 text-sm text-[#444]">
              {[
                { type: '1 : 1', desc: 'One GL row matched to one Subledger row.' },
                { type: 'N : 1', desc: 'Multiple GL rows matched to one Subledger row (GL split payments).' },
                { type: '1 : N', desc: 'One GL row matched to multiple Subledger rows (Sub split payments).' },
              ].map(({ type, desc }) => (
                <div key={type} className="bg-[#f0f4ff] rounded-lg p-3">
                  <p className="font-bold text-[#2563eb] font-mono mb-1">{type}</p>
                  <p className="text-xs">{desc}</p>
                </div>
              ))}
            </div>
          </SubSection>

          <SubSection title="Review & Override">
            <p className="text-sm text-[#444]">
              Probabilistic matches are surfaced in a dedicated review step. You can accept or reject
              each match individually. Rejected matches return to the residual pool for Stage 3.
              Accepted matches are locked and included in the final consolidation.
            </p>
          </SubSection>

          <SubSection title="Dynamic configuration">
            <p className="text-sm text-[#444]">
              Weights, threshold, date tolerance window, and amount percentage tolerance are all
              configurable via the matching config step. Custom values are stored in
              <code className="bg-[#f0f0f0] px-1 rounded text-xs mx-1">matching_config.probabilistic</code>
              and used at runtime. Default values apply when no custom config is confirmed.
            </p>
          </SubSection>
        </Card>

        {/* Stage 3 */}
        <Card className="mb-5 border-l-4 border-l-[#7c3aed]">
          <div className="flex items-start gap-3 mb-3">
            <span className="bg-[#7c3aed] text-white text-xs font-bold px-2.5 py-0.5 rounded-full shrink-0 mt-0.5">Stage 3</span>
            <h3 className="text-base font-semibold text-[#1a1a1a]">AI-Assisted Matching</h3>
          </div>

          <SubSection title="Purpose">
            <p className="text-sm text-[#444] leading-relaxed">
              AI matching handles the long tail of residuals — edge cases, structural data quality
              issues, or transactions that require contextual reasoning beyond numeric similarity.
              AI matches are <strong>advisory only</strong>: every suggestion must be explicitly
              accepted or rejected by a human reviewer.
            </p>
          </SubSection>

          <SubSection title="Process">
            <p className="text-sm text-[#444]">
              The remaining residual pool is sent to the AI model along with contextual metadata
              (vendor lists, amount ranges, entity names). The model returns match suggestions with
              a confidence score and a plain-English reasoning narrative explaining why each pair
              is a likely match.
            </p>
          </SubSection>

          <SubSection title="Review & Override">
            <p className="text-sm text-[#444]">
              AI suggestions appear in a dedicated review step with the full reasoning narrative
              visible. You can accept (locks the match into the final list), reject (sends both
              rows to the unmatched export), or override manually (enter any GL/Subledger ID pair
              you choose).
            </p>
          </SubSection>
        </Card>

        {/* Preprocessing */}
        <Card>
          <p className="text-sm font-semibold text-[#1a1a1a] mb-2">Preprocessing — Vendor Normalization</p>
          <p className="text-sm text-[#444] mb-3 leading-relaxed">
            Before any matching runs, vendor names are normalized through a three-tier cascade
            so that equivalent vendor names (e.g. "Acme Corp.", "ACME CORPORATION", "Acme") resolve
            to a single canonical form used as the join key.
          </p>
          <div className="space-y-2 text-sm text-[#444]">
            {[
              { tier: 'Tier 1', label: 'Rule-based', desc: 'Alias map lookup → lowercase → punctuation removal → suffix stripping → stopword removal.' },
              { tier: 'Tier 2', label: 'Fuzzy NLP', desc: 'Token-sort fuzzy ratio (rapidfuzz) against the Subledger vendor list. Threshold: 90% similarity.' },
              { tier: 'Tier 3', label: 'AI stub', desc: 'AI-assisted resolution for vendors that pass through Tiers 1 and 2 without a match.' },
            ].map(({ tier, label, desc }) => (
              <div key={tier} className="flex gap-3 bg-[#f9fafb] rounded-lg px-3 py-2">
                <span className="font-mono font-semibold text-[#555] w-14 shrink-0">{tier}</span>
                <span className="font-semibold text-[#333] w-24 shrink-0">{label}</span>
                <span>{desc}</span>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* ── 3. AI Usage ── */}
      <Section id="ai-usage" title="How AI Is Used">
        <p className="text-[#333] leading-relaxed mb-5">
          AI plays a deliberate, bounded role in the pipeline. It is used where human-like
          reasoning adds genuine value, and explicitly excluded from the deterministic and
          probabilistic layers where reproducibility and auditability require pure mathematics.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#16a34a] mb-3">Where AI is used</p>
            <ul className="space-y-3 text-sm text-[#444]">
              {[
                {
                  label: 'Stage 3 — AI Matching',
                  desc: 'Suggests matches for residual records that passed through deterministic and probabilistic stages without a match. Advisory only — all suggestions require human acceptance.',
                },
                {
                  label: 'Chat Assistant',
                  desc: 'An in-app conversational interface for exploring your data, understanding match results, and asking questions about the reconciliation in plain English.',
                },
                {
                  label: 'Column Mapping (Phase 1 analysis)',
                  desc: 'AI analyzes uploaded column names and sample data to suggest semantic roles (ID, Vendor, Amount, Date, Entity) for each column, which you confirm or adjust.',
                },
                {
                  label: 'Matching Config Suggestions',
                  desc: 'After preprocessing, AI inspects data characteristics (date spread, amount distribution, entity cardinality) and suggests deterministic scenarios and probabilistic weight configurations.',
                },
              ].map(({ label, desc }) => (
                <li key={label}>
                  <p className="font-semibold text-[#1a1a1a] mb-0.5">{label}</p>
                  <p>{desc}</p>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <p className="text-xs font-semibold uppercase tracking-wider text-[#98002E] mb-3">Where AI is NOT used</p>
            <ul className="space-y-3 text-sm text-[#444]">
              {[
                {
                  label: 'Deterministic Matching',
                  desc: 'Pure rule evaluation. Every match produced here is 100% reproducible and explainable without any model involvement.',
                },
                {
                  label: 'Probabilistic Scoring',
                  desc: 'Entirely mathematical — fuzzy string ratios and numeric similarity functions. No language model is involved at any point.',
                },
                {
                  label: 'Vendor Normalization (Tiers 1 & 2)',
                  desc: 'String preprocessing rules and fuzzy matching with rapidfuzz. Deterministic and auditable.',
                },
                {
                  label: 'Final Consolidation & Export',
                  desc: 'Pure aggregation of accepted matches from all three stages. No AI inference is applied during consolidation or export generation.',
                },
              ].map(({ label, desc }) => (
                <li key={label}>
                  <p className="font-semibold text-[#1a1a1a] mb-0.5">{label}</p>
                  <p>{desc}</p>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <Card className="mb-4">
          <p className="text-sm font-semibold text-[#1a1a1a] mb-3">Model and API</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm text-[#444]">
            <div>
              <p className="text-xs font-semibold text-[#888] uppercase tracking-wider mb-1">Default model</p>
              <p className="font-mono text-[#333]">gpt-4o-mini</p>
              <p className="text-xs text-[#888] mt-0.5">OpenAI API. Configurable per session.</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-[#888] uppercase tracking-wider mb-1">Prompt strategy</p>
              <p>System prompt includes session state, column mapping, aggregated statistics, and up to 500 rows of raw data per side. Raw transaction data is never cached or stored beyond the request.</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-[#888] uppercase tracking-wider mb-1">Human-in-the-loop</p>
              <p>All AI-generated outputs (match suggestions, column role assignments, config recommendations) require explicit user confirmation before they affect the reconciliation state.</p>
            </div>
          </div>
        </Card>

        <Card>
          <p className="text-sm font-semibold text-[#1a1a1a] mb-2">Advisory-only principle</p>
          <p className="text-sm text-[#444] leading-relaxed">
            AI suggestions never automatically advance the pipeline state. A human must review and
            confirm every AI output before it is applied. This ensures that the final reconciliation
            is always defensible in an audit context — every match has a traceable, human-approved
            justification. The AI's reasoning narrative is stored in the session snapshot and
            included in the export package for full auditability.
          </p>
        </Card>
      </Section>

      {/* Footer nav */}
      <div className="border-t border-[#d1d1d1] pt-6 flex justify-between items-center text-sm text-[#888]">
        <span>Recon.AI Documentation</span>
        <Link to="/faq" className="text-[#98002E] hover:text-[#6b0022] font-medium transition-colors">
          View FAQ →
        </Link>
      </div>
    </div>
  )
}
