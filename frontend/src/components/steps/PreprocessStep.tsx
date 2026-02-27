import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { runPreprocess } from '@/api/endpoints'
import type { PreprocessingResponse, NormalizationEntry } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

type SortKey = keyof NormalizationEntry
type SortDir = 'asc' | 'desc'

function NormalizationTable({ entries }: { entries: NormalizationEntry[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('original_vendor')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [filter, setFilter] = useState('')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const filtered = entries.filter(
    (e) =>
      e.original_vendor.toLowerCase().includes(filter.toLowerCase()) ||
      e.normalized_vendor.toLowerCase().includes(filter.toLowerCase()) ||
      (e.matched_to ?? '').toLowerCase().includes(filter.toLowerCase()),
  )

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] ?? ''
    const bv = b[sortKey] ?? ''
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true })
    return sortDir === 'asc' ? cmp : -cmp
  })

  const Th = ({ k, label }: { k: SortKey; label: string }) => (
    <th
      onClick={() => handleSort(k)}
      className="text-left py-2 px-3 text-xs font-medium text-gray-600 cursor-pointer hover:bg-gray-100 select-none"
    >
      {label}
      {sortKey === k ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  )

  const tierColor: Record<string, string> = {
    tier1: 'bg-green-100 text-green-700',
    tier2: 'bg-blue-100 text-blue-700',
    tier3: 'bg-purple-100 text-purple-700',
  }

  return (
    <div>
      <div className="mb-3">
        <input
          type="text"
          placeholder="Filter vendors…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border border-gray-200 rounded-md px-3 py-1.5 text-sm w-full max-w-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <span className="text-xs text-gray-400 ml-3">{sorted.length} of {entries.length} entries</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <Th k="original_vendor" label="Original Vendor" />
              <Th k="normalized_vendor" label="Normalized" />
              <Th k="matched_to" label="Matched To" />
              <Th k="match_source" label="Tier" />
              <Th k="similarity_score" label="Similarity" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((entry, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="py-2 px-3 font-mono text-xs text-gray-800">{entry.original_vendor}</td>
                <td className="py-2 px-3 font-mono text-xs text-gray-700">{entry.normalized_vendor}</td>
                <td className="py-2 px-3 font-mono text-xs text-gray-600">
                  {entry.matched_to ?? <span className="text-gray-300">—</span>}
                </td>
                <td className="py-2 px-3">
                  <span
                    className={[
                      'text-xs px-2 py-0.5 rounded-full font-medium',
                      tierColor[entry.match_source] ?? 'bg-gray-100 text-gray-600',
                    ].join(' ')}
                  >
                    {entry.match_source}
                  </span>
                </td>
                <td className="py-2 px-3 text-xs text-gray-600">
                  {entry.similarity_score != null
                    ? `${(entry.similarity_score * 100).toFixed(1)}%`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PreprocessResult({ data }: { data: PreprocessingResponse }) {
  const s = data.normalization_summary
  return (
    <div className="mt-6 space-y-5">
      {/* Summary */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">Normalization Summary</h4>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {[
            ['Total GL Vendors', s.total_unique_gl_vendors],
            ['Tier 1', s.tier1_count],
            ['Tier 2', s.tier2_count],
            ['Tier 3', s.tier3_count],
            ['Threshold', `${(s.threshold_used * 100).toFixed(0)}%`],
            ['Alias Ver.', s.alias_version],
          ].map(([label, value]) => (
            <div key={String(label)} className="bg-gray-50 rounded-md p-3 text-center">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-sm font-bold text-gray-900 mt-0.5">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Map table */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">
          Vendor Normalization Map ({data.vendor_normalization_map.length} entries)
        </h4>
        <NormalizationTable entries={data.vendor_normalization_map} />
      </div>

      <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-800">
        Preprocessing complete. State: <strong>{data.state}</strong>
      </div>
    </div>
  )
}

export default function PreprocessStep({ sessionId, onSuccess }: Props) {
  const mutation = useMutation({
    mutationFn: () => runPreprocess(sessionId),
    onSuccess,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Preprocess — Vendor Normalization</h2>
      <p className="text-sm text-gray-500 mb-5">
        Run the 3-tier vendor normalization pipeline (alias map → NLP fuzzy → AI stub) to produce
        consistent vendor keys for downstream matching.
      </p>

      {mutation.error && (
        <div className="mb-4">
          <ErrorDisplay error={mutation.error} onRefresh={onSuccess} />
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {mutation.isPending ? 'Preprocessing…' : 'Run Preprocessing'}
      </button>

      {mutation.data && <PreprocessResult data={mutation.data} />}
    </div>
  )
}
