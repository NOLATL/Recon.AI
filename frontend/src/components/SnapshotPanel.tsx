import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listSnapshots, getSnapshot } from '@/api/endpoints'
import JsonViewer from './JsonViewer'
import ErrorDisplay from './ErrorDisplay'

interface Props {
  sessionId: string
}

export default function SnapshotPanel({ sessionId }: Props) {
  const [selectedPhase, setSelectedPhase] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['snapshots', sessionId],
    queryFn: () => listSnapshots(sessionId),
  })

  const detailQuery = useQuery({
    queryKey: ['snapshot', sessionId, selectedPhase],
    queryFn: () => getSnapshot(sessionId, selectedPhase!),
    enabled: !!selectedPhase,
  })

  return (
    <div className="bg-white border border-gray-200 rounded-lg h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-medium text-gray-900">Snapshots</h3>
        <p className="text-xs text-gray-500 mt-0.5">Pre-transition state captures</p>
      </div>

      {listQuery.isLoading && (
        <p className="text-xs text-gray-400 p-4">Loading…</p>
      )}
      {listQuery.error && (
        <div className="p-4">
          <ErrorDisplay error={listQuery.error} />
        </div>
      )}

      {listQuery.data && (
        <div className="flex-1 overflow-y-auto">
          {listQuery.data.snapshots.length === 0 && (
            <p className="text-xs text-gray-400 p-4">No snapshots yet.</p>
          )}

          {/* Snapshot list */}
          <ul className="divide-y divide-gray-100">
            {listQuery.data.snapshots.map((snap) => (
              <li key={snap.integrity_hash}>
                <button
                  onClick={() =>
                    setSelectedPhase((prev) =>
                      prev === snap.pre_transition_state
                        ? null
                        : snap.pre_transition_state,
                    )
                  }
                  className={[
                    'w-full text-left px-4 py-3 text-xs transition-colors hover:bg-gray-50',
                    selectedPhase === snap.pre_transition_state
                      ? 'bg-blue-50'
                      : '',
                  ].join(' ')}
                >
                  <div className="font-mono font-medium text-gray-800">
                    {snap.pre_transition_state}
                  </div>
                  <div className="text-gray-400 mt-0.5">
                    {new Date(snap.captured_at).toLocaleString()}
                  </div>
                  <div className="text-gray-400">by {snap.triggered_by}</div>
                  <div className="font-mono text-gray-300 text-[10px] mt-0.5 truncate">
                    {snap.integrity_hash}
                  </div>
                </button>
              </li>
            ))}
          </ul>

          {/* Snapshot detail */}
          {selectedPhase && (
            <div className="border-t border-gray-200 p-4">
              <h4 className="text-xs font-semibold text-gray-700 mb-2">
                Snapshot: {selectedPhase}
              </h4>
              {detailQuery.isLoading && (
                <p className="text-xs text-gray-400">Loading…</p>
              )}
              {detailQuery.error && (
                <ErrorDisplay error={detailQuery.error} />
              )}
              {detailQuery.data && (
                <>
                  <div className="text-xs text-gray-500 mb-2 space-y-0.5">
                    <div>Captured: {new Date(detailQuery.data.captured_at).toLocaleString()}</div>
                    <div className="font-mono truncate text-[10px] text-gray-400">
                      Hash: {detailQuery.data.integrity_hash}
                    </div>
                  </div>
                  <JsonViewer data={detailQuery.data.runtime_snapshot} maxHeight="300px" />
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
