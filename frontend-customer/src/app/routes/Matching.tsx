import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Loader2, Check, Circle } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  getSessionStatus,
  getConsolidation,
  confirmDeterministicReview,
  runProbabilistic,
  confirmProbabilisticReview,
  runAi,
  confirmAiReview,
  runConsolidate,
  ApiError,
  RECON_SESSION_ID_KEY,
} from '@/api/endpoints'
import { cn } from '@/lib/utils'

// White card styling (matches Load & Clean Data page)
const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

type PhaseStatus = 'queued' | 'running' | 'complete'

const PHASES = [
  { id: 'deterministic', label: 'Deterministic Matching' },
  { id: 'probabilistic', label: 'Probabilistic Matching' },
  { id: 'ai', label: 'AI Matching' },
] as const

/** States where the pipeline is fully complete (consolidation done). */
const TERMINAL_STATES = new Set([
  'final_consolidated',
  'finalized',
])

/** States that still need pipeline actions. */
const ACTIONABLE_STATES = new Set([
  'deterministic_complete',
  'deterministic_review_complete',
  'probabilistic_complete',
  'probabilistic_review_complete',
  'ai_suggested',
  'ai_review_complete',
])

function PhaseStatusIcon({ status }: { status: PhaseStatus }) {
  if (status === 'queued') return <Circle className="size-4 text-muted-foreground" aria-hidden />
  if (status === 'running') return <Loader2 className="size-4 animate-spin text-primary" aria-hidden />
  return <Check className="size-4 text-green-600 dark:text-green-500" aria-hidden />
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
      <div
        className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  )
}

// Shape of intermediate match responses (only the field we need)
interface MatchWithId { match_id: string }

const POLL_INTERVAL_MS = 2000

export function Matching() {
  const navigate = useNavigate()
  const [sessionId] = useState<string | null>(() =>
    localStorage.getItem(RECON_SESSION_ID_KEY)
  )
  const [phaseStatuses, setPhaseStatuses] = useState<PhaseStatus[]>(['queued', 'queued', 'queued'])
  const [recordCounts, setRecordCounts] = useState([0, 0, 0])
  const [amountsByPhase, setAmountsByPhase] = useState([0, 0, 0])
  const [currentState, setCurrentState] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Refs persist match IDs across poll ticks without causing re-renders.
  // If the user refreshes mid-pipeline these are empty; we confirm with []
  // which still advances the state machine (matches stay "pending").
  const probMatchIdsRef = useRef<string[]>([])
  const aiMatchIdsRef   = useRef<string[]>([])

  // Mutex: prevents the polling interval from firing a second advance while
  // an async step is already in flight.
  const executingRef = useRef(false)

  useEffect(() => {
    if (!sessionId) return

    let cancelled = false

    /**
     * Advance the backend state machine one logical step from `state`.
     * For review phases (probabilistic_complete, ai_suggested) we use stored
     * match IDs so every match is accepted.  On a cold page load those refs
     * are empty and we confirm with an empty decisions array — the state still
     * advances, though those matches won't appear in the final consolidation.
     */
    const advancePipeline = async (state: string) => {
      if (executingRef.current || cancelled) return
      if (!ACTIONABLE_STATES.has(state)) return

      executingRef.current = true
      try {
        switch (state) {
          // ── Phase 4A: confirm det review (no match IDs needed) ────────────
          case 'deterministic_complete':
            await confirmDeterministicReview(sessionId)
            break

          // ── Phase 5: run probabilistic + immediately auto-accept all ──────
          case 'deterministic_review_complete': {
            const res = await runProbabilistic(sessionId) as { matches?: MatchWithId[] }
            probMatchIdsRef.current = (res?.matches ?? []).map(m => m.match_id)
            const decisions = probMatchIdsRef.current.map(id => ({ match_id: id, decision: 'accepted' as const }))
            await confirmProbabilisticReview(sessionId, decisions)
            break
          }

          // ── Phase 5A: confirm probabilistic review (edge case: page refresh) ─
          case 'probabilistic_complete': {
            const decisions = probMatchIdsRef.current.map(id => ({ match_id: id, decision: 'accepted' as const }))
            await confirmProbabilisticReview(sessionId, decisions)
            break
          }

          // ── Phase 6: run AI + immediately auto-accept all ─────────────────
          case 'probabilistic_review_complete': {
            const res = await runAi(sessionId) as { suggestions?: MatchWithId[] }
            aiMatchIdsRef.current = (res?.suggestions ?? []).map(m => m.match_id)
            const decisions = aiMatchIdsRef.current.map(id => ({ match_id: id, decision: 'accepted' as const }))
            await confirmAiReview(sessionId, decisions)
            break
          }

          // ── Phase 6A: confirm AI review (edge case: page refresh) ─────────
          case 'ai_suggested': {
            const decisions = aiMatchIdsRef.current.map(id => ({ match_id: id, decision: 'accepted' as const }))
            await confirmAiReview(sessionId, decisions)
            break
          }

          // ── Phase 7: final consolidation ──────────────────────────────────
          case 'ai_review_complete':
            await runConsolidate(sessionId)
            break
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          // 409 = already in target state or wrong precondition → safe to skip
          return
        }
        if (!cancelled) {
          const isAbort = err instanceof Error && (err.name === 'AbortError' || err.message.includes('aborted'))
          setError(isAbort
            ? 'A pipeline step timed out. The backend may still be processing — refresh the page to resume.'
            : err instanceof Error ? err.message : 'Pipeline step failed')
        }
      } finally {
        executingRef.current = false
      }
    }

    const poll = async () => {
      try {
        const res = await getSessionStatus(sessionId)
        if (cancelled) return

        setCurrentState(res.current_state)

        // When in terminal state, use consolidation for accurate per-phase breakdown.
        // Session status has ai_suggested: 0 after AI matches move to final bucket.
        if (TERMINAL_STATES.has(res.current_state)) {
          try {
            const cons = await getConsolidation(sessionId)
            if (!cancelled) {
              const glAmtMap = new Map<string, number>()
              ;(cons.gl_records ?? []).forEach((r: Record<string, unknown>) => {
                const id = String(r.gl_id ?? '')
                if (id) glAmtMap.set(id, Number(r.amount ?? 0))
              })
              const amtByLayer = { deterministic: 0, probabilistic: 0, ai: 0 }
              ;(cons.final_matches ?? []).forEach((m: Record<string, unknown>) => {
                const layer = String(m.layer ?? '')
                const glIds = (m.record_ids_A as string[]) ?? []
                if (layer in amtByLayer) {
                  amtByLayer[layer as keyof typeof amtByLayer] += glIds.reduce(
                    (sum, id) => sum + (glAmtMap.get(id) ?? 0),
                    0
                  )
                }
              })
              // Count GL rows per layer (record_ids_A), not match pairs,
              // so N:1 probabilistic matches are counted correctly.
              const glCount = { deterministic: 0, probabilistic: 0, ai: 0 }
              ;(cons.final_matches ?? []).forEach((m: Record<string, unknown>) => {
                const layer = String(m.layer ?? '')
                const glIds = (m.record_ids_A as string[]) ?? []
                if (layer in glCount) glCount[layer as keyof typeof glCount] += glIds.length
              })
              setRecordCounts([glCount.deterministic, glCount.probabilistic, glCount.ai])
              setAmountsByPhase([
                amtByLayer.deterministic,
                amtByLayer.probabilistic,
                amtByLayer.ai,
              ])
            }
          } catch {
            // Fall back to session status if consolidation unavailable
            const summary = res.matching_summary ?? {}
            const amounts = res.matching_amount_summary ?? {}
            setRecordCounts([
              summary.deterministic ?? 0,
              summary.probabilistic ?? 0,
              summary.ai_suggested ?? 0,
            ])
            setAmountsByPhase([
              amounts.deterministic ?? 0,
              amounts.probabilistic ?? 0,
              amounts.ai_suggested ?? 0,
            ])
          }
        } else {
          const summary    = res.matching_summary ?? {}
          const amounts    = res.matching_amount_summary ?? {}
          const detCount   = summary.deterministic ?? 0
          const probCount  = summary.probabilistic ?? 0
          const aiCount    = summary.ai_suggested ?? summary.final ?? 0
          setRecordCounts([detCount, probCount, aiCount])
          setAmountsByPhase([
            amounts.deterministic ?? 0,
            amounts.probabilistic ?? 0,
            amounts.ai_suggested ?? 0,
          ])
        }

        // Derive display status for each of the three phases
        const nextStatuses: PhaseStatus[] = ['queued', 'queued', 'queued']
        const s = res.current_state
        if (TERMINAL_STATES.has(s)) {
          nextStatuses[0] = 'complete'
          nextStatuses[1] = 'complete'
          nextStatuses[2] = 'complete'
        } else if (s === 'ai_review_complete') {
          nextStatuses[0] = 'complete'
          nextStatuses[1] = 'complete'
          nextStatuses[2] = 'complete'
        } else if (s === 'ai_suggested' || s === 'probabilistic_review_complete') {
          nextStatuses[0] = 'complete'
          nextStatuses[1] = 'complete'
          nextStatuses[2] = 'running'
        } else if (s === 'probabilistic_complete' || s === 'deterministic_review_complete') {
          nextStatuses[0] = 'complete'
          nextStatuses[1] = 'running'
        } else if (s === 'deterministic_complete' || s === 'preprocessed') {
          nextStatuses[0] = 'complete'
          nextStatuses[1] = 'running'
        } else if (s === 'profiled' || s === 'files_loaded') {
          nextStatuses[0] = 'running'
        }
        setPhaseStatuses(nextStatuses)

        // Drive the pipeline forward (no-op if executingRef.current or terminal)
        await advancePipeline(res.current_state)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch status')
        }
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [sessionId])

  const allComplete =
    currentState === 'finalized' ||
    currentState === 'final_consolidated'
  const totalProcessed = recordCounts.reduce((a, b) => a + b, 0)
  const totalAmount = amountsByPhase.reduce((a, b) => a + b, 0)
  const currentPhaseIndex = phaseStatuses.findIndex((s) => s === 'running')
  const currentPhaseLabel =
    currentPhaseIndex >= 0 ? PHASES[currentPhaseIndex].label : null

  const handleCancel = () => {
    navigate('/load-files')
  }

  if (!sessionId) {
    return (
      <PageLayout title="Matching" description="Reconciliation pipeline: deterministic, probabilistic, and AI matching.">
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-sm text-[#1a1a1a]">
              No session. Upload files and run matching from the Load & Clean Data page.
            </p>
            <Button variant="outline" className="mt-4" onClick={() => navigate('/load-files')}>
              Go to Load & Clean Data
            </Button>
          </CardContent>
        </Card>
      </PageLayout>
    )
  }

  if (error) {
    return (
      <PageLayout title="Matching" description="Reconciliation pipeline: deterministic, probabilistic, and AI matching.">
        <Card className={whiteCardClass}>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" className="mt-4" onClick={() => navigate('/load-files')}>
              Back to Load & Clean Data
            </Button>
          </CardContent>
        </Card>
      </PageLayout>
    )
  }

  return (
    <PageLayout title="Matching" description="Reconciliation pipeline: deterministic, probabilistic, and AI matching.">
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Pipeline Status</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            Reconciliation runs through deterministic, probabilistic, and AI matching.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {PHASES.map((phase, i) => (
            <div
              key={phase.id}
              className={cn(
                'flex flex-col gap-2 rounded-lg border border-gray-200 p-4',
                phaseStatuses[i] === 'running' && 'border-primary/30 bg-primary/5'
              )}
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <PhaseStatusIcon status={phaseStatuses[i]} />
                  <span className="font-medium text-foreground">{phase.label}</span>
                </div>
                <div className="flex items-center gap-4 text-sm tabular-nums text-muted-foreground">
                  {phaseStatuses[i] !== 'queued' && (
                    <span className="font-medium text-foreground">
                      ${amountsByPhase[i].toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  )}
                  <span>
                    {phaseStatuses[i] === 'complete'
                      ? recordCounts[i].toLocaleString()
                      : phaseStatuses[i] === 'running'
                        ? `${recordCounts[i].toLocaleString()} processed`
                        : '—'}{' '}
                    GL rows
                  </span>
                </div>
              </div>
              <ProgressBar
                value={phaseStatuses[i] === 'complete' ? 100 : phaseStatuses[i] === 'running' ? 50 : 0}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Run Status</CardTitle>
          <CardDescription className="text-[#1a1a1a]">Current run progress and summary.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-sm text-muted-foreground">Current Status</p>
              <p className="font-medium text-foreground">
                {currentPhaseLabel ?? (allComplete ? 'Complete' : '—')}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Total GL rows matched</p>
              <p className="text-lg font-semibold tabular-nums text-foreground">
                {totalProcessed.toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Total amount processed</p>
              <p className="text-lg font-semibold tabular-nums text-foreground">
                {totalAmount > 0
                  ? `$${totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : '—'}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-4">
        {!allComplete && (
          <Button variant="brand" onClick={handleCancel}>
            Cancel Run
          </Button>
        )}
        {allComplete && (
          <Button asChild size="lg" variant="brand">
            <Link to="/high-level-analysis">
              View Results
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        )}
      </div>
    </PageLayout>
  )
}
