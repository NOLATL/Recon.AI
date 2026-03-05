import { useState } from 'react'
import { cn } from '@/lib/utils'

/** Mock histogram data: label + count for simple bar display */
export interface HistogramBucket {
  label: string
  count: number
}

interface ColumnHistogramHoverProps {
  columnName: string
  buckets: HistogramBucket[]
  className?: string
}

export function ColumnHistogramHover({
  columnName,
  buckets,
  className,
}: ColumnHistogramHoverProps) {
  const [hover, setHover] = useState(false)
  const maxCount = Math.max(1, ...buckets.map((b) => b.count))

  return (
    <span
      className={cn('relative inline-block', className)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <span className="cursor-default underline decoration-dotted decoration-muted-foreground/50 underline-offset-2">
        {columnName}
      </span>
      {hover && buckets.length > 0 && (
        <div
          className="absolute left-0 top-full z-50 mt-1 min-w-[180px] rounded-lg border border-border bg-popover p-3 shadow-lg"
          role="tooltip"
        >
          <p className="mb-2 text-xs font-medium text-popover-foreground">
            Distribution
          </p>
          <div className="space-y-1.5">
            {buckets.slice(0, 8).map((b) => (
              <div key={b.label} className="flex items-center gap-2 text-xs">
                <span className="w-16 truncate text-muted-foreground" title={b.label}>
                  {b.label}
                </span>
                <div className="h-4 flex-1 min-w-[60px] rounded bg-muted overflow-hidden">
                  <div
                    className="h-full rounded bg-primary/80"
                    style={{ width: `${(b.count / maxCount) * 100}%` }}
                  />
                </div>
                <span className="w-6 text-right tabular-nums text-muted-foreground">
                  {b.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </span>
  )
}
