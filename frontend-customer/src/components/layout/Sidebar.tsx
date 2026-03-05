import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  GitMerge,
  BarChart3,
  FileSearch,
  Menu,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: 'Landing', icon: LayoutDashboard },
  { to: '/load-files', label: 'Load Files', icon: Upload },
  { to: '/matching', label: 'Matching', icon: GitMerge },
  { to: '/high-level-analysis', label: 'High-Level Analysis', icon: BarChart3 },
  { to: '/detailed-analysis', label: 'Detailed Analysis', icon: FileSearch },
] as const

export function Sidebar() {
  const [mobileOpen, setMobileOpen] = useState(false)

  const navContent = (
    <nav className="flex flex-col gap-1 p-4">
      <div className="mb-4 px-2">
        <span className="text-lg font-semibold text-sidebar-foreground">
          ReconAI
        </span>
      </div>
      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                : 'text-sidebar-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground'
            )
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  )

  return (
    <>
      {/* Mobile menu button */}
      <div className="fixed left-4 top-4 z-50 md:hidden">
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMobileOpen((open) => !open)}
        >
          {mobileOpen ? <X className="size-4" /> : <Menu className="size-4" />}
        </Button>
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar: drawer on mobile, fixed on desktop */}
      <aside
        className={cn(
          'fixed left-0 top-0 z-40 h-full w-64 border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-transform duration-200 ease-out md:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Spacer for mobile menu button on small screens */}
        <div className="h-16 md:h-4" />
        {navContent}
      </aside>
    </>
  )
}
