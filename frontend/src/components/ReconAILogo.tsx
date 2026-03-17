/**
 * ReconAILogo — brand mark for ReconAI.
 *
 * The mark is two slim vertical columns (GL + Subledger) connected by a
 * thin horizontal bridge at the midpoint — a visual metaphor for
 * "two sides being reconciled." Clean, geometric, audit-grade.
 *
 * variant="light" → white mark + white wordmark  (use on dark/void backgrounds)
 * variant="dark"  → dark (#111) mark + dark wordmark (use on red hero backgrounds)
 */

interface Props {
  variant?: 'light' | 'dark'
  className?: string
  /** Show only the icon without the wordmark */
  iconOnly?: boolean
  size?: 'sm' | 'md' | 'lg'
}

const SIZE_MAP = {
  sm: { icon: 20, text: 'text-sm' },
  md: { icon: 26, text: 'text-base' },
  lg: { icon: 34, text: 'text-xl' },
}

export default function ReconAILogo({
  variant = 'light',
  className = '',
  iconOnly = false,
  size = 'md',
}: Props) {
  const fill = variant === 'dark' ? '#111111' : '#FFFFFF'
  const textColor = variant === 'dark' ? 'text-[#111111]' : 'text-white'
  const { icon: iconSize, text: textSize } = SIZE_MAP[size]

  const w = iconSize
  const h = iconSize * 1.2

  // Column dimensions
  const colW = w * 0.18
  const colH = h * 0.72
  const colY = h * 0.14
  const gap = w * 0.22

  // Left column x
  const leftX = w * 0.5 - gap / 2 - colW
  // Right column x
  const rightX = w * 0.5 + gap / 2

  // Bridge: horizontal bar at 55% height
  const bridgeY = colY + colH * 0.50
  const bridgeH = h * 0.07
  const bridgeX = leftX
  const bridgeW = rightX + colW - leftX

  // Small accent dots at top of each column
  const dotR = colW * 0.7
  const dotLeftCx = leftX + colW / 2
  const dotRightCx = rightX + colW / 2
  const dotY = colY - dotR * 0.4

  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      {/* Icon mark */}
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        {/* Left column */}
        <rect
          x={leftX}
          y={colY}
          width={colW}
          height={colH}
          rx={colW * 0.5}
          fill={fill}
        />
        {/* Right column */}
        <rect
          x={rightX}
          y={colY}
          width={colW}
          height={colH}
          rx={colW * 0.5}
          fill={fill}
        />
        {/* Bridge connector */}
        <rect
          x={bridgeX}
          y={bridgeY}
          width={bridgeW}
          height={bridgeH}
          rx={bridgeH * 0.5}
          fill={fill}
          opacity={0.9}
        />
        {/* Accent dots (top) */}
        <circle cx={dotLeftCx} cy={dotY} r={dotR} fill={fill} opacity={0.5} />
        <circle cx={dotRightCx} cy={dotY} r={dotR} fill={fill} opacity={0.5} />
      </svg>

      {/* Wordmark */}
      {!iconOnly && (
        <span className={`font-bold tracking-tight ${textSize} ${textColor}`}>
          Recon<span style={{ color: variant === 'dark' ? '#CC2529' : 'rgba(255,255,255,0.7)' }}>AI</span>
        </span>
      )}
    </div>
  )
}
