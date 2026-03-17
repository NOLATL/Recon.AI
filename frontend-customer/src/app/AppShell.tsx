import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'

export function AppShell() {
  const { pathname } = useLocation()
  const isLanding = pathname === '/'

  if (isLanding) {
    return (
      <div className="min-h-screen" style={{ background: 'var(--primary)' }}>
        <Outlet />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <main className="min-h-screen pl-64 bg-background text-[#1a1a1a] [--foreground:#1a1a1a] [--muted-foreground:#1a1a1a] [--card-foreground:#1a1a1a]">
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
