import { ConflictError, ValidationApiError } from '@/api/client'

interface Props {
  error: unknown
  onRefresh?: () => void
}

export default function ErrorDisplay({ error, onRefresh }: Props) {
  if (error instanceof ValidationApiError) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4 text-sm">
        <p className="font-medium text-red-800 mb-2">Validation errors</p>
        <ul className="space-y-1">
          {error.errors.map((e, i) => (
            <li key={i} className="text-red-700">
              <span className="font-mono text-xs text-red-500">
                {e.loc.join(' → ')}
              </span>{' '}
              {e.msg}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (error instanceof ConflictError) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-md p-4 text-sm">
        <p className="font-medium text-amber-800 mb-1">State conflict</p>
        <p className="text-amber-700">{error.message}</p>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="mt-2 text-amber-700 underline hover:text-amber-900 text-xs"
          >
            Refresh status
          </button>
        )}
      </div>
    )
  }

  if (error instanceof Error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-4 text-sm">
        <p className="font-medium text-red-800">Error</p>
        <p className="text-red-700 mt-1">{error.message}</p>
      </div>
    )
  }

  return (
    <div className="bg-red-50 border border-red-200 rounded-md p-4 text-sm text-red-700">
      An unexpected error occurred.
    </div>
  )
}
