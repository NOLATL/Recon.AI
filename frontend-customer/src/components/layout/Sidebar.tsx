import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  GitMerge,
  BarChart3,
  FileSearch,
  Package,
  RotateCcw,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { RECON_SESSION_ID_KEY } from '@/api/endpoints'
import { LogoWithMatchedBackground } from '@/components/LogoWithMatchedBackground'

const navItems = [
  { to: '/', label: 'Home', icon: LayoutDashboard },
  { to: '/load-files', label: 'Load & Clean Data', icon: Upload },
  { to: '/matching', label: 'Matching', icon: GitMerge },
  { to: '/high-level-analysis', label: 'Matched Analysis', icon: BarChart3 },
  { to: '/detailed-analysis', label: 'Unmatched Analysis', icon: FileSearch },
  { to: '/export', label: 'Export', icon: Package },
] as const

export function Sidebar() {
  const navigate = useNavigate()

  const handleResetSession = () => {
    localStorage.removeItem(RECON_SESSION_ID_KEY)
    navigate('/load-files')
  }

  return (
    <aside className="fixed left-0 top-0 z-50 h-full w-64 bg-[#98002E]">
      {/* Logo: centered in pane, higher z-index so visible above other layers */}
      <div className="relative z-50 flex justify-center pt-6 pb-4 min-h-[4.5rem]">
        <LogoWithMatchedBackground
          background="primary"
          alt="Recon.AI"
          className="h-[6.75rem] w-auto object-contain"
        />
      </div>
      <nav className="flex flex-col gap-1 p-4">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium text-white transition-colors',
                  isActive
                    ? 'bg-white text-[#1a1a1a]'
                    : 'bg-[#333333] hover:bg-[#444444]'
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
          <div className="mt-4 border-t border-white/20 pt-4">
            <button
              type="button"
              onClick={handleResetSession}
              className="flex w-full items-center justify-start gap-3 rounded-full bg-[#333333] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#444444]"
            >
              <RotateCcw className="size-4 shrink-0" aria-hidden />
              Reset Session
            </button>
          </div>
        </nav>
    </aside>
  )
}
