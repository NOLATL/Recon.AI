import { Loader2, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type { DeterministicScenarioConfig, ProbabilisticConfig } from '@/api/endpoints'

const ALL_PROB_FIELDS = ['vendor', 'amount', 'date', 'entity', 'currency'] as const

const whiteCardClass =
  'bg-white border-gray-200 shadow-[0_2px_8px_rgba(0,0,0,0.08)] rounded-2xl [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]'

// Fields that can be toggled on/off as match criteria
const MATCH_FIELDS = ['vendor', 'amount', 'date', 'entity', 'currency'] as const

// -----------------------------------------------------------------------
// ScenarioEditor — one card per scenario with toggle buttons
// -----------------------------------------------------------------------

interface ScenarioEditorProps {
  scenario: DeterministicScenarioConfig
  index: number
  onChange: (s: DeterministicScenarioConfig) => void
  onRemove: () => void
}

function ScenarioEditor({ scenario, index, onChange, onRemove }: ScenarioEditorProps) {
  const isSelected = (field: string) => scenario.match_fields.includes(field)

  const toggleField = (field: string) => {
    if (isSelected(field) && scenario.match_fields.length === 1) return  // keep at least one field
    const next = isSelected(field)
      ? scenario.match_fields.filter((f) => f !== field)
      : [...scenario.match_fields, field]
    onChange({ ...scenario, match_fields: next })
  }

  const dateTol      = scenario.date_tolerance_days ?? 0
  const amountAbs    = scenario.amount_tolerance_abs ?? 0
  const amountPctRaw = scenario.amount_tolerance_pct ?? 0
  // Display pct as 0–100 for UX, store as 0–1 in config
  const amountPctDisplay = parseFloat((amountPctRaw * 100).toFixed(4))

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      {/* Header row: scenario label + confidence + remove */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-[#1a1a1a] shrink-0">
          Scenario {index + 1}
        </span>
        <div className="flex items-center gap-0.5 shrink-0">
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={Math.round(scenario.confidence_score * 100)}
            onChange={(e) =>
              onChange({ ...scenario, confidence_score: (parseInt(e.target.value, 10) || 0) / 100 })
            }
            className="w-14 border border-gray-300 rounded px-1 py-0.5 text-center text-xs text-[#009966] font-semibold tabular-nums focus:outline-none focus:ring-1 focus:ring-[#98002E]"
          />
          <span className="text-xs text-[#009966] font-semibold">%</span>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="ml-auto flex items-center justify-center p-1 rounded hover:bg-red-50 text-red-500 transition-colors"
          title="Remove scenario"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Toggle buttons row */}
      <div className="flex flex-wrap items-center gap-2">
        {MATCH_FIELDS.map((field) => {
          const selected = isSelected(field)
          return (
            <div key={field} className="flex items-center gap-1.5">
              {/* Toggle pill */}
              <button
                type="button"
                onClick={() => toggleField(field)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  selected
                    ? 'bg-[#009966] text-white hover:bg-[#007a52]'
                    : 'bg-gray-100 text-[#555] hover:bg-gray-200'
                }`}
              >
                {field}
              </button>

              {/* Date tolerance inline inputs */}
              {selected && field === 'date' && (
                <div className="flex items-center gap-1 text-xs text-[#1a1a1a]">
                  <span className="text-gray-400">±</span>
                  <input
                    type="number"
                    min={0}
                    value={dateTol}
                    onChange={(e) =>
                      onChange({ ...scenario, date_tolerance_days: parseInt(e.target.value, 10) || 0 })
                    }
                    className="w-12 border border-gray-300 rounded px-1.5 py-0.5 text-center text-xs focus:outline-none focus:ring-1 focus:ring-[#98002E]"
                  />
                  <span className="text-gray-500">days</span>
                </div>
              )}

              {/* Amount tolerance inline inputs */}
              {selected && field === 'amount' && (
                <div className="flex items-center gap-1 text-xs text-[#1a1a1a]">
                  <span className="text-gray-400">±$</span>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    value={amountAbs}
                    onChange={(e) =>
                      onChange({ ...scenario, amount_tolerance_abs: parseFloat(e.target.value) || 0 })
                    }
                    className="w-14 border border-gray-300 rounded px-1.5 py-0.5 text-center text-xs focus:outline-none focus:ring-1 focus:ring-[#98002E]"
                  />
                  <span className="text-gray-400">or</span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={0.1}
                    value={amountPctDisplay}
                    onChange={(e) =>
                      onChange({
                        ...scenario,
                        amount_tolerance_pct: parseFloat(e.target.value) / 100 || 0,
                      })
                    }
                    className="w-14 border border-gray-300 rounded px-1.5 py-0.5 text-center text-xs focus:outline-none focus:ring-1 focus:ring-[#98002E]"
                  />
                  <span className="text-gray-500">%</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// -----------------------------------------------------------------------
// Main section component
// -----------------------------------------------------------------------

interface Props {
  rationale: string
  scenarios: DeterministicScenarioConfig[]
  probConfig: ProbabilisticConfig
  onScenariosChange: (s: DeterministicScenarioConfig[]) => void
  onProbChange: (p: ProbabilisticConfig) => void
  onConfirm: () => void
  confirming: boolean
  error: string | null
  title?: string
}

export function MatchingConfigSection({
  rationale,
  scenarios,
  probConfig,
  onScenariosChange,
  onProbChange,
  onConfirm,
  confirming,
  error,
  title = 'Matching Configuration',
}: Props) {
  const weightSum = Object.values(probConfig.weights).reduce((s, v) => s + v, 0)
  const weightsOk =
    Object.keys(probConfig.weights).length === 0 || Math.abs(weightSum - 1.0) < 0.02
  const canConfirm = weightsOk && !confirming

  const updateScenario = (i: number, updated: DeterministicScenarioConfig) => {
    const next = scenarios.map((s, idx) => (idx === i ? updated : s))
    onScenariosChange(next)
  }

  const removeScenario = (i: number) => {
    onScenariosChange(scenarios.filter((_, idx) => idx !== i))
  }

  const usedFields = Object.keys(probConfig.weights)
  const remainingFields = ALL_PROB_FIELDS.filter((f) => !usedFields.includes(f))

  const setWeight = (key: string, val: number) => {
    onProbChange({ ...probConfig, weights: { ...probConfig.weights, [key]: val } })
  }

  const addWeightField = () => {
    if (remainingFields.length === 0) return
    onProbChange({
      ...probConfig,
      weights: { ...probConfig.weights, [remainingFields[0]]: 0 },
    })
  }

  const removeWeightField = (key: string) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { [key]: _removed, ...rest } = probConfig.weights
    onProbChange({ ...probConfig, weights: rest })
  }

  const renameWeightField = (oldKey: string, newKey: string) => {
    const val = probConfig.weights[oldKey]
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { [oldKey]: _removed, ...rest } = probConfig.weights
    onProbChange({ ...probConfig, weights: { ...rest, [newKey]: val } })
  }

  return (
    <section>
      <Card className={whiteCardClass}>
        <CardHeader>
          <CardTitle className="text-[#1a1a1a]">{title}</CardTitle>
          <CardDescription className="text-[#1a1a1a]">
            AI has recommended matching scenarios and probabilistic weights based on your data.
            Toggle fields on (green) or off to customise each scenario, then confirm.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {rationale && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-[#1a1a1a] leading-relaxed">
              {rationale}
            </div>
          )}

          {/* Deterministic scenarios */}
          {scenarios.length > 0 && (
            <div>
              <p className="text-sm font-semibold text-[#1a1a1a] mb-2">Deterministic Scenarios</p>
              <div className="space-y-2">
                {scenarios.map((s, i) => (
                  <ScenarioEditor
                    key={s.scenario_id}
                    scenario={s}
                    index={i}
                    onChange={(updated) => updateScenario(i, updated)}
                    onRemove={() => removeScenario(i)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Probabilistic weights */}
          {Object.keys(probConfig.weights).length > 0 && (
            <div>
              <p className="text-sm font-semibold text-[#1a1a1a] mb-2">
                Probabilistic Weights
                <span
                  className={`ml-2 text-xs font-normal ${
                    weightsOk ? 'text-[#009966]' : 'text-destructive'
                  }`}
                >
                  (sum = {weightSum.toFixed(2)}
                  {weightsOk ? ' ✓' : ' — must equal 1.00'})
                </span>
              </p>

              {/*
                Grid layout — 5 columns, fixed widths except slider (1fr):
                [dropdown 6rem] [criteria 11rem] [slider 1fr] [value 2.5rem] [remove 1.5rem]
                All rows share the same column tracks so sliders stay aligned.
              */}
              <div
                className="space-y-2"
                style={{ display: 'grid', gridTemplateColumns: '6rem 11rem 1fr 2.5rem 1.5rem', alignItems: 'center', gap: '0 0.5rem' }}
              >
                {Object.entries(probConfig.weights).map(([key, val]) => {
                  const availableForRow = [key, ...remainingFields]
                  return (
                    <>
                      {/* Col 1: field selector */}
                      <select
                        key={`${key}-sel`}
                        value={key}
                        onChange={(e) => renameWeightField(key, e.target.value)}
                        className="border border-gray-300 rounded px-1.5 py-1 text-xs text-[#1a1a1a] bg-white focus:outline-none focus:ring-1 focus:ring-[#98002E] capitalize w-full"
                      >
                        {availableForRow.map((f) => (
                          <option key={f} value={f} className="capitalize">{f}</option>
                        ))}
                      </select>

                      {/* Col 2: inline criteria (date tolerance / amount % tolerance / empty) */}
                      <div key={`${key}-crit`} className="flex items-center gap-1 text-xs text-[#1a1a1a]">
                        {key === 'date' && (
                          <>
                            <span className="text-gray-400 shrink-0">±</span>
                            <input
                              type="number"
                              min={0}
                              value={probConfig.date_tolerance_days}
                              onChange={(e) =>
                                onProbChange({
                                  ...probConfig,
                                  date_tolerance_days: parseInt(e.target.value, 10) || 0,
                                })
                              }
                              className="w-14 border border-gray-300 rounded px-1.5 py-0.5 text-center text-xs focus:outline-none focus:ring-1 focus:ring-[#98002E]"
                            />
                            <span className="text-gray-500 shrink-0">days</span>
                          </>
                        )}
                        {key === 'amount' && (
                          <>
                            <span className="text-gray-400 shrink-0">±</span>
                            <input
                              type="number"
                              min={0}
                              max={100}
                              step={0.1}
                              value={parseFloat((probConfig.amount_pct_tolerance * 100).toFixed(4))}
                              onChange={(e) =>
                                onProbChange({
                                  ...probConfig,
                                  amount_pct_tolerance: parseFloat(e.target.value) / 100 || 0,
                                })
                              }
                              className="w-14 border border-gray-300 rounded px-1.5 py-0.5 text-center text-xs focus:outline-none focus:ring-1 focus:ring-[#98002E]"
                            />
                            <span className="text-gray-500 shrink-0">%</span>
                          </>
                        )}
                      </div>

                      {/* Col 3: weight slider */}
                      <input
                        key={`${key}-slider`}
                        type="range"
                        min={0}
                        max={1}
                        step={0.01}
                        value={val}
                        onChange={(e) => setWeight(key, parseFloat(e.target.value))}
                        className="w-full accent-[#98002E]"
                      />

                      {/* Col 4: numeric value */}
                      <span key={`${key}-val`} className="text-right tabular-nums font-mono text-xs text-[#1a1a1a]">
                        {val.toFixed(2)}
                      </span>

                      {/* Col 5: remove button */}
                      <button
                        key={`${key}-rm`}
                        type="button"
                        onClick={() => removeWeightField(key)}
                        className="flex items-center justify-center p-1 rounded hover:bg-red-50 text-red-500 transition-colors"
                        title="Remove criterion"
                      >
                        <X className="size-3.5" />
                      </button>
                    </>
                  )
                })}
              </div>

              {/* Add criterion */}
              {remainingFields.length > 0 && (
                <button
                  type="button"
                  onClick={addWeightField}
                  className="mt-2 flex items-center gap-1.5 text-xs text-[#009966] hover:text-[#007a52] font-medium transition-colors"
                >
                  <Plus className="size-3.5" />
                  Add criterion
                </button>
              )}

            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button variant="brand" disabled={!canConfirm} onClick={onConfirm}>
            {confirming ? (
              <>
                <Loader2 className="size-4 animate-spin mr-2" aria-hidden />
                Confirming…
              </>
            ) : (
              'Confirm Matching Config'
            )}
          </Button>
        </CardContent>
      </Card>
    </section>
  )
}
