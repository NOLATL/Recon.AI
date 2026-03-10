/**
 * MatchingFunnel — pure SVG trapezoid funnel (no recharts dependency).
 *
 * Each layer is a trapezoid whose top width = this layer's proportion of the
 * total and whose bottom width = the next layer's proportion.  That creates a
 * smooth, continuously narrowing funnel.
 *
 * Labels are stacked inside each trapezoid: name / record count / dollar amount.
 * When a layer is too narrow to hold the text comfortably the font is scaled
 * down; very narrow layers (< 90 px average width) render their label to the
 * right with a short connector line.
 */

export interface FunnelStep {
  name: string
  value: number
  amount?: number
  fill?: string
}

interface MatchingFunnelProps {
  data: FunnelStep[]
  className?: string
}

// Colours map to layer order: Total / Deterministic / Probabilistic / AI / Unmatched
const DEFAULT_FILLS = [
  '#64748b', // slate   — Total
  '#16a34a', // green   — Deterministic
  '#2563eb', // blue    — Probabilistic
  '#7c3aed', // purple  — AI
  '#d97706', // amber   — Unmatched
]

const VIEW_W = 560   // SVG viewBox width
const VIEW_H = 350   // 25 % taller than the previous 280-px height
const MIN_FRAC = 0.04  // narrowest a layer may render (4 % of total width)

function fmtAmount(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}

export function MatchingFunnel({ data, className }: MatchingFunnelProps) {
  if (data.length === 0) return null

  const maxValue = data[0]?.value || 1
  const layerH   = VIEW_H / data.length

  // Width fraction for each layer (clamped to [MIN_FRAC, 1.0])
  const fracs = data.map((d, i) =>
    i === 0 ? 1.0 : Math.min(1, Math.max(MIN_FRAC, d.value / maxValue))
  )

  return (
    <div className={className}>
      <svg
        width="100%"
        height={VIEW_H}
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
        aria-label="Matching funnel chart"
      >
        {data.map((item, i) => {
          const fill    = item.fill ?? DEFAULT_FILLS[i % DEFAULT_FILLS.length]
          const topFrac = fracs[i]
          // Bottom of this layer = top of next layer (taper slightly for the last)
          const botFrac = i < data.length - 1
            ? fracs[i + 1]
            : Math.max(MIN_FRAC, fracs[i] * 0.88)

          const topW = topFrac * VIEW_W
          const botW = botFrac * VIEW_W
          const y    = i * layerH

          // Trapezoid corners (centred in viewBox)
          const tlx = (VIEW_W - topW) / 2
          const trx = (VIEW_W + topW) / 2
          const blx = (VIEW_W - botW) / 2
          const brx = (VIEW_W + botW) / 2
          const points = `${tlx},${y} ${trx},${y} ${brx},${y + layerH} ${blx},${y + layerH}`

          // Centre of the trapezoid
          const cx   = VIEW_W / 2
          const cy   = y + layerH / 2
          const avgW = (topW + botW) / 2

          const showAmount = item.amount != null && item.amount > 0
          const isNarrow   = avgW < 90

          // Font sizes scale with available width
          const nameFontSize  = Math.min(13, Math.max(9,  avgW / 13))
          const valueFontSize = Math.min(11, Math.max(8,  avgW / 17))
          const amtFontSize   = Math.min(10, Math.max(7,  avgW / 20))

          // Vertical stack spacing
          const lineH      = valueFontSize * 1.45
          const lines      = showAmount ? 3 : 2
          const totalTextH = nameFontSize + (lines - 1) * lineH
          const nameY      = cy - totalTextH / 2 + nameFontSize * 0.85
          const countY     = nameY + lineH
          const amtY       = nameY + lineH * 2

          // Right-side label geometry (narrow layers)
          const rightLabelX = trx + 10
          const rightNameFsz = 11
          const rightValFsz  = 10

          return (
            <g key={item.name}>
              {/* Trapezoid */}
              <polygon points={points} fill={fill} />

              {/* Separator line between layers */}
              {i > 0 && (
                <line
                  x1={tlx} y1={y} x2={trx} y2={y}
                  stroke="white" strokeWidth={1.5} strokeOpacity={0.45}
                />
              )}

              {isNarrow ? (
                /* Right-side label with connector */
                <>
                  <line
                    x1={trx + 1} y1={cy}
                    x2={rightLabelX} y2={cy}
                    stroke={fill} strokeWidth={1} strokeOpacity={0.75}
                  />
                  <text
                    x={rightLabelX + 2}
                    y={cy - (showAmount ? 14 : 7)}
                    fontSize={rightNameFsz} fontWeight="600" fill={fill}
                  >
                    {item.name}
                  </text>
                  <text
                    x={rightLabelX + 2}
                    y={cy + (showAmount ? 0 : 7)}
                    fontSize={rightValFsz} fill={fill} opacity={0.85}
                  >
                    {item.value.toLocaleString()} records
                  </text>
                  {showAmount && (
                    <text
                      x={rightLabelX + 2} y={cy + 14}
                      fontSize={rightValFsz - 1} fill={fill} opacity={0.70}
                    >
                      {fmtAmount(item.amount!)}
                    </text>
                  )}
                </>
              ) : (
                /* Inside label stack */
                <>
                  <text
                    x={cx} y={nameY}
                    textAnchor="middle"
                    fontSize={nameFontSize} fontWeight="600" fill="white"
                  >
                    {item.name}
                  </text>
                  <text
                    x={cx} y={countY}
                    textAnchor="middle"
                    fontSize={valueFontSize} fill="rgba(255,255,255,0.92)"
                  >
                    {item.value.toLocaleString()} records
                  </text>
                  {showAmount && (
                    <text
                      x={cx} y={amtY}
                      textAnchor="middle"
                      fontSize={amtFontSize} fill="rgba(255,255,255,0.80)"
                    >
                      {fmtAmount(item.amount!)}
                    </text>
                  )}
                </>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
