import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api/endpoints'

export default function HealthIndicator() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-gray-400">
        <span className="w-2 h-2 rounded-full bg-gray-300 animate-pulse" />
        API
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-red-600">
        <span className="w-2 h-2 rounded-full bg-red-500" />
        API offline
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1.5 text-xs text-green-700">
      <span className="w-2 h-2 rounded-full bg-green-500" />
      API online
    </div>
  )
}
