import { ALL_STATES } from '@/schemas'
import type { ReconciliationState } from '@/schemas'

const STATE_LABELS: Record<ReconciliationState, string> = {
  initialized: 'Initialized',
  files_loaded: 'Files Loaded',
  profiled: 'Profiled',
  preprocessed: 'Preprocessed',
  deterministic_complete: 'Det. Complete',
  deterministic_review_complete: 'Det. Review',
  probabilistic_complete: 'Prob. Complete',
  probabilistic_review_complete: 'Prob. Review',
  ai_suggested: 'AI Suggested',
  ai_review_complete: 'AI Review',
  final_consolidated: 'Consolidated',
  finalized: 'Finalized',
}

interface Props {
  currentState: ReconciliationState
}

export default function StateMachineTimeline({ currentState }: Props) {
  const currentIdx = ALL_STATES.indexOf(currentState)

  return (
    <div className="overflow-x-auto">
      <div className="flex items-center gap-0 min-w-max">
        {ALL_STATES.map((state, idx) => {
          const isDone = idx < currentIdx
          const isCurrent = idx === currentIdx

          return (
            <div key={state} className="flex items-center">
              {/* Node */}
              <div className="flex flex-col items-center">
                <div
                  className={[
                    'w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold border-2 flex-shrink-0 transition-all duration-200',
                    isDone
                      ? 'bg-bdo-red border-bdo-red text-white'
                      : isCurrent
                        ? 'bg-void border-bdo-red-light text-bdo-red-light shadow-red-glow ring-2 ring-bdo-red/20 ring-offset-1 ring-offset-void-surface'
                        : 'bg-void-elevated border-void-border text-white/25',
                  ].join(' ')}
                >
                  {isDone ? (
                    <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" width="10" height="10">
                      <path d="M2 5l2.5 2.5L8 3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    idx + 1
                  )}
                </div>
                <span
                  className={[
                    'mt-1.5 text-[9px] text-center max-w-[70px] leading-tight',
                    isCurrent
                      ? 'text-bdo-red-light font-semibold'
                      : isDone
                        ? 'text-white/50'
                        : 'text-white/20',
                  ].join(' ')}
                >
                  {STATE_LABELS[state]}
                </span>
              </div>

              {/* Connector */}
              {idx < ALL_STATES.length - 1 && (
                <div
                  className={[
                    'h-0.5 w-5 mx-1 flex-shrink-0 mb-5 transition-all duration-200',
                    idx < currentIdx ? 'bg-bdo-red/50' : 'bg-void-border',
                  ].join(' ')}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
