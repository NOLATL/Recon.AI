import { Outlet, useLocation, NavLink } from 'react-router-dom'
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
        <div className="flex justify-end items-center px-6 py-2.5 border-b border-[#d1d1d1] bg-background">
          <nav className="flex items-center gap-5">
            <NavLink
              to="/documentation"
              className={({ isActive }) =>
                `text-sm font-medium transition-colors ${isActive ? 'text-[#98002E]' : 'text-[#777] hover:text-[#1a1a1a]'}`
              }
            >
              Documentation
            </NavLink>
            <NavLink
              to="/faq"
              className={({ isActive }) =>
                `text-sm font-medium transition-colors ${isActive ? 'text-[#98002E]' : 'text-[#777] hover:text-[#1a1a1a]'}`
              }
            >
              FAQ
            </NavLink>
          </nav>
        </div>
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
