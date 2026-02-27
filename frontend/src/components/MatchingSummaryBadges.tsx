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

export default function MatchingSummaryBadges({ summary }: Props) {
  const entries = Object.entries(summary)
  if (entries.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {entries.map(([key, count]) => (
        <div
          key={key}
          className="flex items-center gap-1.5 bg-gray-100 rounded-full px-3 py-1 text-xs"
        >
          <span className="text-gray-500">{BUCKET_LABELS[key] ?? key}</span>
          <span className="font-semibold text-gray-800">{count}</span>
        </div>
      ))}
    </div>
  )
}
