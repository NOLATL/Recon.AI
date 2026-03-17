import { createPortal } from 'react-dom'
import { useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/** Histogram bar: label + count */
export interface HistogramBucket {
  label: string
  count: number
}

interface ColumnHistogramHoverProps {
  columnName: string
  buckets: HistogramBucket[]
  description?: string
  className?: string
}

export function ColumnHistogramHover({
  columnName,
  buckets,
  description,
  className,
}: ColumnHistogramHoverProps) {
  const triggerRef = useRef<HTMLSpanElement>(null)
  const [hover, setHover] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const maxCount = Math.max(1, ...buckets.map((b) => b.count))
  const hasContent = buckets.length > 0 || !!description

  useLayoutEffect(() => {
    if (!hover || !hasContent || !triggerRef.current) {
      setPosition(null)
      return
    }
    const rect = triggerRef.current.getBoundingClientRect()
    setPosition({ top: rect.bottom + 4, left: rect.left })
  }, [hover, hasContent])

  const tooltipContent =
    hover &&
    hasContent &&
    position && (
      <div
        className="fixed z-[9999] w-[320px] overflow-hidden rounded-lg border border-border bg-[#1a1a1a] p-3 shadow-lg"
        role="tooltip"
        style={{
          top: position.top,
          left: position.left,
          boxSizing: 'border-box',
        }}
      >
        {description && (
          <div className="mb-2 w-full min-w-0 overflow-hidden">
            <p
              className="w-full min-w-0 whitespace-normal text-xs text-white leading-relaxed"
              style={{
                overflowWrap: 'break-word',
                wordBreak: 'normal',
                maxWidth: '272px',
              }}
            >
              {description}
            </p>
          </div>
        )}
        {buckets.length > 0 && (
          <>
            <p className="mb-1.5 text-xs font-medium text-white">Distribution</p>
            <div className="space-y-1.5">
              {buckets.slice(0, 8).map((b) => (
                <div key={b.label} className="flex flex-col gap-1 text-xs">
                  <span className="break-words text-white" title={b.label}>
                    {b.label}
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="h-4 min-w-[60px] flex-1 overflow-hidden rounded bg-white/20">
                      <div
                        className="h-full rounded bg-primary/80"
                        style={{ width: `${(b.count / maxCount) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-right tabular-nums text-white">
                      {b.count}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    )

  return (
    <>
      <span
        ref={triggerRef}
        className={cn('relative inline-block', className)}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        <span className="cursor-default underline decoration-dotted decoration-muted-foreground/50 underline-offset-2">
          {columnName}
        </span>
      </span>
      {tooltipContent && createPortal(tooltipContent, document.body)}
    </>
  )
}
