interface Props {
  summary: Record<string, number>
}

const BUCKET_LABELS: Record<string, string> = {
  deterministic: 'Deterministic',
  probabilistic: 'Probabilistic',
  ai_suggested: 'AI',
  final: 'Final',
  rejected: 'Rejected',
}

const BUCKET_STYLES: Record<string, string> = {
  deterministic: 'bg-bdo-red/15 text-bdo-red-light border border-bdo-red/25',
  probabilistic: 'bg-violet-500/15 text-violet-300 border border-violet-500/25',
  ai_suggested:  'bg-sky-500/15 text-sky-300 border border-sky-500/25',
  final:         'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25',
  rejected:      'bg-white/5 text-white/40 border border-white/10',
}

export default function MatchingSummaryBadges({ summary }: Props) {
  const entries = Object.entries(summary)
  if (entries.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {entries.map(([key, count]) => (
        <div
          key={key}
          className={`status-badge ${BUCKET_STYLES[key] ?? 'bg-white/5 text-white/50 border border-white/10'}`}
        >
          <span>{BUCKET_LABELS[key] ?? key}</span>
          <span className="font-bold">{count}</span>
        </div>
      ))}
    </div>
  )
}
