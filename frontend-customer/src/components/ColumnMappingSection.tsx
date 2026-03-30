import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type { AnalyzeColumnsResponse, ColumnRole, SideColumnMap, ColumnStat } from '@/api/endpoints'
import { ColumnHistogramHover } from '@/components/upload/ColumnHistogramHover'

const ROLES: { value: ColumnRole | ''; label: string }[] = [
  { value: '',         label: '— select role —' },
  { value: 'id',       label: 'ID' },
  { value: 'vendor',   label: 'Vendor' },
  { value: 'amount',   label: 'Amount' },
  { value: 'date',     label: 'Date' },
  { value: 'entity',   label: 'Entity' },
  { value: 'currency', label: 'Currency' },
  { value: 'ignore',   label: 'Ignore' },
]

const REQUIRED_ROLES: ColumnRole[] = ['id', 'vendor', 'amount']

const COLUMN_DESCRIPTIONS: Record<string, string> = {
  gl_id:                'Unique identifier for each General Ledger transaction record.',
  subledger_id:         'Unique identifier for each Subledger transaction record.',
  entity:               'Business or legal entity associated with the transaction.',
  account_code:         'General Ledger account code used to classify the transaction.',
  vendor_name:          'Name of the vendor or supplier involved in the transaction.',
  transaction_date:     'Date on which the transaction was recorded or posted.',
  amount:               'Transaction monetary amount in the specified currency.',
  currency:             'ISO 4217 currency code for the transaction amount.',
  exception_flag:       'Indicates whether this transaction has been flagged as an exception requiring review.',
  reference_id:         'Reference identifier linking this Subledger record to its General Ledger counterpart.',
  materiality_threshold:'Dollar threshold above which a difference is considered material.',
}

const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

function fmt(val: number | null | undefined, decimals = 0): string {
  if (val == null) return '—'
  return val.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function expandLabel(label: string): string {
  if (label.trim().toUpperCase() === 'GL') return 'General Ledger'
  return label
}

interface SideTableProps {
  label: string
  suggestions: AnalyzeColumnsResponse['side_a_suggestions']
  mapping: SideColumnMap
  onChange: (m: SideColumnMap) => void
  stats?: ColumnStat[]
}

function SideTable({ label, suggestions, mapping, onChange, stats }: SideTableProps) {
  const setRole = (columnName: string, role: ColumnRole | '') => {
    const next = { ...mapping }
    if (role && role !== 'ignore') {
      for (const [r, col] of Object.entries(next)) {
        if (col === columnName && r !== role) delete (next as Record<string, string>)[r]
      }
      for (const [r, col] of Object.entries(next)) {
        if (r === role && col !== columnName) delete (next as Record<string, string>)[r]
      }
    }
    if (role === '') {
      for (const [r, col] of Object.entries(next)) {
        if (col === columnName) delete (next as Record<string, string>)[r]
      }
    } else if (role !== 'ignore') {
      (next as Record<string, string>)[role] = columnName
    }
    onChange(next)
  }

  const currentRoleFor = (colName: string): ColumnRole | '' => {
    for (const [r, col] of Object.entries(mapping)) {
      if (col === colName) return r as ColumnRole
    }
    return ''
  }

  // Build lookup from column name → stat row (populated after profiling)
  const statMap = new Map<string, ColumnStat>()
  if (stats) {
    for (const s of stats) statMap.set(s.name, s)
  }
  const hasStats = statMap.size > 0

  return (
    <div>
      <p className="text-xl font-bold text-[#1a1a1a] mb-3">{expandLabel(label)}</p>
      <div className="overflow-x-auto">
        <table className="text-sm border-collapse w-full" style={{ minWidth: hasStats ? '1100px' : '680px' }}>
          <thead>
            <tr className="bg-[#333333] text-white">
              <th className="text-left py-2 px-3 font-semibold whitespace-nowrap">Mapped Role</th>
              <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Confidence</th>
              <th className="text-left py-2 px-3 font-semibold whitespace-nowrap">Column Name</th>
              <th className="text-left py-2 px-3 font-semibold">Sample Values</th>
              {hasStats && (
                <>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Cnt Unique</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Cnt Null</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Null %</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Min</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Max</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Sum</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Avg</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Std Dev</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Median</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Max Len</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Min Len</th>
                  <th className="text-right py-2 px-3 font-semibold whitespace-nowrap">Blanks</th>
                  <th className="text-left py-2 px-3 font-semibold whitespace-nowrap">Mode</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {suggestions.map((s, i) => {
              const stat = statMap.get(s.column_name)
              return (
                <tr key={s.column_name} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  {/* Col 1: Role dropdown */}
                  <td className="py-2 px-3">
                    <select
                      value={currentRoleFor(s.column_name)}
                      onChange={(e) => setRole(s.column_name, e.target.value as ColumnRole | '')}
                      className="text-sm border border-gray-300 rounded px-2 py-1 bg-white text-[#1a1a1a] focus:outline-none focus:ring-1 focus:ring-[#98002E] min-w-[9rem]"
                    >
                      {ROLES.map((r) => (
                        <option key={r.value} value={r.value}>{r.label}</option>
                      ))}
                    </select>
                  </td>
                  {/* Col 2: Confidence % */}
                  <td className="py-2 px-3 text-right tabular-nums text-[#1a1a1a] whitespace-nowrap">
                    {s.confidence > 0 ? (
                      <span className="font-semibold text-[#009966]">{Math.round(s.confidence * 100)}%</span>
                    ) : '—'}
                  </td>
                  {/* Col 3: Column name — with hover tooltip when stats available */}
                  <td className="py-2 px-3 font-mono text-[#1a1a1a] whitespace-nowrap">
                    {hasStats ? (
                      <ColumnHistogramHover
                        columnName={s.column_name}
                        buckets={stat?.histogram ?? []}
                        description={COLUMN_DESCRIPTIONS[s.column_name]}
                      />
                    ) : (
                      s.column_name
                    )}
                  </td>
                  {/* Col 4: Sample values */}
                  <td
                    className="py-2 px-3 text-[#1a1a1a] max-w-[260px] truncate"
                    title={s.sample_values.join(', ')}
                  >
                    {s.sample_values.slice(0, 4).join(', ')}
                  </td>
                  {/* Stat columns — only rendered when profiling data is available */}
                  {hasStats && (
                    <>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat ? stat.unique_count.toLocaleString() : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat ? stat.null_count.toLocaleString() : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat ? `${Math.round(stat.null_pct)}%` : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat
                          ? stat.data_type === 'numeric'
                            ? fmt(stat.min as number)
                            : stat.data_type === 'date'
                            ? String(stat.min ?? '—')
                            : '—'
                          : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat
                          ? stat.data_type === 'numeric'
                            ? fmt(stat.max as number)
                            : stat.data_type === 'date'
                            ? String(stat.max ?? '—')
                            : '—'
                          : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'numeric' ? fmt(stat.sum) : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'numeric' ? fmt(stat.mean) : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'numeric' ? fmt(stat.std) : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'numeric' ? fmt(stat.median) : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'string' ? (stat.max_len ?? '—') : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'string' ? (stat.min_len ?? '—') : '—'}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums text-xs text-[#1a1a1a] whitespace-nowrap">
                        {stat?.data_type === 'string' ? (stat.blank_count ?? '—') : '—'}
                      </td>
                      <td
                        className="py-2 px-3 text-xs text-[#1a1a1a] max-w-[100px] truncate"
                        title={stat?.data_type === 'string' ? (stat.mode ?? undefined) : undefined}
                      >
                        {stat?.data_type === 'string' ? (stat.mode ?? '—') : '—'}
                      </td>
                    </>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {/* Missing required roles warning */}
      {(() => {
        const missing = REQUIRED_ROLES.filter((r) => !mapping[r])
        return missing.length > 0 ? (
          <p className="mt-2 text-sm text-amber-700">
            Required roles not yet assigned: <strong>{missing.join(', ')}</strong>
          </p>
        ) : null
      })()}
    </div>
  )
}

interface Props {
  analysis: AnalyzeColumnsResponse
  sideAMap: SideColumnMap
  sideBMap: SideColumnMap
  onSideAChange: (m: SideColumnMap) => void
  onSideBChange: (m: SideColumnMap) => void
  onConfirm: () => void
  confirming: boolean
  confirmingMessage?: string
  error: string | null
  glStats?: ColumnStat[]
  slStats?: ColumnStat[]
}

export function ColumnMappingSection({
  analysis,
  sideAMap,
  sideBMap,
  onSideAChange,
  onSideBChange,
  onConfirm,
  confirming,
  confirmingMessage = 'Loading statistics…',
  error,
  glStats,
  slStats,
}: Props) {
  const missingA = REQUIRED_ROLES.filter((r) => !sideAMap[r])
  const missingB = REQUIRED_ROLES.filter((r) => !sideBMap[r])
  const canConfirm = missingA.length === 0 && missingB.length === 0 && !confirming

  return (
    <section>
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">Column Mapping</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            AI has analyzed your files and pre-filled the role for each column. Verify each
            assignment, then confirm to continue. Required roles: ID, Vendor, Amount.
            {(glStats || slStats) && (
              <span className="ml-1 text-[#009966]">
                Descriptive statistics populated — hover a column name for distribution.
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {analysis.analysis_narrative && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-[#1a1a1a] leading-relaxed">
              {analysis.analysis_narrative}
            </div>
          )}
          <SideTable
            label={analysis.side_a_label}
            suggestions={analysis.side_a_suggestions}
            mapping={sideAMap}
            onChange={onSideAChange}
            stats={glStats}
          />
          <SideTable
            label={analysis.side_b_label}
            suggestions={analysis.side_b_suggestions}
            mapping={sideBMap}
            onChange={onSideBChange}
            stats={slStats}
          />
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
          <Button
            variant="brand"
            disabled={!canConfirm}
            onClick={onConfirm}
          >
            {confirming ? (
              <><Loader2 className="size-4 animate-spin mr-2" aria-hidden />{confirmingMessage}</>
            ) : (
              'Confirm Column Mapping'
            )}
          </Button>
        </CardContent>
      </Card>
    </section>
  )
}
