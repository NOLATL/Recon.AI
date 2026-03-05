import type React from 'react'
import {
  Funnel,
  FunnelChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

export interface FunnelStep {
  name: string
  value: number
  amount?: number
  fill?: string
}

const DEFAULT_FILLS = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
]

interface MatchingFunnelProps {
  data: FunnelStep[]
  className?: string
}

function RightLabelContent(props: {
  x?: number
  y?: number
  payload?: { value?: number; amount?: number; name?: string }
}) {
  const { x = 0, y = 0, payload } = props
  const value = payload?.value ?? 0
  const amount = payload?.amount
  return (
    <text x={x} y={y} textAnchor="start" className="fill-muted-foreground" fontSize={11}>
      <tspan x={x} dy={0}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </tspan>
      {amount != null && (
        <tspan x={x} dy="1.2em" fontSize={10}>
          ${amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
        </tspan>
      )}
    </text>
  )
}

export function MatchingFunnel({ data, className }: MatchingFunnelProps) {
  const withFills = data.map((d, i) => ({
    ...d,
    fill: d.fill ?? DEFAULT_FILLS[i % DEFAULT_FILLS.length],
  }))

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={280}>
        <FunnelChart layout="vertical" margin={{ top: 20, right: 120, bottom: 20, left: 20 }}>
          <Tooltip
            formatter={(value: unknown) =>
              [typeof value === 'number' ? value.toLocaleString() : String(value ?? ''), 'Records'] as [React.ReactNode, string]
            }
          />
          <Funnel
            dataKey="value"
            data={withFills}
            isAnimationActive={false}
          >
            <LabelList
              position="center"
              dataKey="name"
              className="fill-foreground"
              fontSize={12}
            />
            <LabelList
              position="right"
              dataKey="value"
              content={<RightLabelContent />}
              offset={8}
            />
          </Funnel>
        </FunnelChart>
      </ResponsiveContainer>
    </div>
  )
}
