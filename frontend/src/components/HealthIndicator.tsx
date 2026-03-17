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
      <div className="flex items-center gap-1.5 text-xs text-white/40">
        <span className="w-1.5 h-1.5 rounded-full bg-white/30 animate-pulse" />
        API
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-bdo-red-light">
        <span className="w-1.5 h-1.5 rounded-full bg-bdo-red" />
        API offline
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1.5 text-xs text-emerald-400">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
      API online
    </div>
  )
}
