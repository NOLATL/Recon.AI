import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { startSession, listSessions } from '@/api/endpoints'
import HealthIndicator from '@/components/HealthIndicator'
import ErrorDisplay from '@/components/ErrorDisplay'

export default function LandingPage() {
  const navigate = useNavigate()

  const sessionsQuery = useQuery({
    queryKey: ['sessions'],
    queryFn: listSessions,
  })

  const startMutation = useMutation({
    mutationFn: startSession,
    onSuccess: (data) => {
      // persist in localStorage so refresh doesn't lose the session
      const stored = JSON.parse(localStorage.getItem('recon_sessions') ?? '[]') as string[]
      if (!stored.includes(data.session_id)) {
        stored.unshift(data.session_id)
        localStorage.setItem('recon_sessions', JSON.stringify(stored))
      }
      navigate(`/sessions/${data.session_id}`)
    },
  })

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">AI Reconciliation Engine</h1>
          <p className="text-sm text-gray-500 mt-0.5">Forward-only automated reconciliation workflow</p>
        </div>
        <HealthIndicator />
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {/* Start new session */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <h2 className="text-lg font-medium text-gray-900 mb-2">New Reconciliation</h2>
          <p className="text-sm text-gray-500 mb-4">
            Start a new session. You will upload GL, Subledger, and Chart of Accounts files and work
            through the full reconciliation pipeline.
          </p>

          {startMutation.error && (
            <div className="mb-4">
              <ErrorDisplay error={startMutation.error} />
            </div>
          )}

          <button
            onClick={() => startMutation.mutate()}
            disabled={startMutation.isPending}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
          >
            {startMutation.isPending ? 'Starting…' : 'Start new reconciliation'}
          </button>
        </div>

        {/* Session list */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium text-gray-900">Sessions</h2>
            <button
              onClick={() => sessionsQuery.refetch()}
              className="text-sm text-blue-600 hover:text-blue-700"
            >
              Refresh
            </button>
          </div>

          {sessionsQuery.isLoading && (
            <p className="text-sm text-gray-500">Loading sessions…</p>
          )}

          {sessionsQuery.error && (
            <ErrorDisplay error={sessionsQuery.error} />
          )}

          {sessionsQuery.data && sessionsQuery.data.session_ids.length === 0 && (
            <p className="text-sm text-gray-500">No sessions yet. Start a new reconciliation above.</p>
          )}

          {sessionsQuery.data && sessionsQuery.data.session_ids.length > 0 && (
            <ul className="divide-y divide-gray-100">
              {sessionsQuery.data.session_ids.map((id) => (
                <li key={id}>
                  <button
                    onClick={() => navigate(`/sessions/${id}`)}
                    className="w-full text-left py-3 px-2 text-sm hover:bg-gray-50 rounded transition-colors flex items-center justify-between group"
                  >
                    <span className="font-mono text-gray-700">{id}</span>
                    <span className="text-xs text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity">
                      Open →
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  )
}
