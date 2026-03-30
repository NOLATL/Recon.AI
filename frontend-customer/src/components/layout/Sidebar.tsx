import { useState, useEffect } from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  GitMerge,
  BarChart3,
  FileSearch,
  Package,
  RotateCcw,
  Lock,
} from 'lucide-react'
import { RECON_SESSION_ID_KEY, getSessionStatus } from '@/api/endpoints'
import { LogoWithMatchedBackground } from '@/components/LogoWithMatchedBackground'

const navItems = [
  { to: '/', label: 'Home', icon: LayoutDashboard },
  { to: '/load-files', label: 'Load & Prep Data', icon: Upload },
  { to: '/matching', label: 'Matching', icon: GitMerge },
  { to: '/high-level-analysis', label: 'Matched Analysis', icon: BarChart3 },
  { to: '/detailed-analysis', label: 'Unmatched Analysis', icon: FileSearch },
  { to: '/export', label: 'Export', icon: Package },
] as const

// Ordered list of all pipeline states (earliest → latest)
const STATE_ORDER = [
  'initialized',
  'files_loaded',
  'column_mapping_complete',
  'profiled',
  'preprocessed',
  'matching_configured',
  'deterministic_complete',
  'deterministic_review_complete',
  'probabilistic_complete',
  'probabilistic_review_complete',
  'ai_suggested',
  'ai_review_complete',
  'final_consolidated',
  'finalized',
]

// Minimum state required to navigate to each route (null = always open)
const UNLOCK_THRESHOLD: Record<string, string | null> = {
  '/': null,
  '/load-files': null,             // always accessible — starting point after Restart
  '/matching': 'matching_configured',
  '/high-level-analysis': 'final_consolidated',
  '/detailed-analysis': 'final_consolidated',
  '/export': 'final_consolidated',
}

function stateIndex(state: string | null): number {
  if (!state) return -1
  const idx = STATE_ORDER.indexOf(state)
  return idx === -1 ? STATE_ORDER.length : idx
}

function isRouteUnlocked(to: string, currentState: string | null, sid: string | null): boolean {
  // Use `in` check so that an explicit null value is not swallowed by ??
  const threshold = to in UNLOCK_THRESHOLD
    ? UNLOCK_THRESHOLD[to]
    : 'finalized'
  if (threshold === null) return true   // Home and Load & Clean are always open
  if (!currentState) return false
  if (stateIndex(currentState) < stateIndex(threshold)) return false
  // Once finalized the export has already run — all pages open
  if (currentState === 'finalized') return true
  // Sequential completion flags: each page's CTA must be clicked before the next unlocks
  if (to === '/detailed-analysis') return !!sid && !!localStorage.getItem(`recon-${sid}-hla-done`)
  if (to === '/export')            return !!sid && !!localStorage.getItem(`recon-${sid}-dla-done`)
  return true
}

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [sessionState, setSessionState] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  // Re-fetch session state whenever the route changes so locks update as user progresses
  useEffect(() => {
    const sid = localStorage.getItem(RECON_SESSION_ID_KEY)
    setSessionId(sid)
    if (!sid) { setSessionState(null); return }
    getSessionStatus(sid)
      .then(res => setSessionState(res.current_state))
      .catch(() => setSessionState(null))
  }, [location.pathname])

  const handleResetSession = () => {
    const sid = localStorage.getItem(RECON_SESSION_ID_KEY)
    if (sid) {
      localStorage.removeItem(`recon-${sid}-hla-done`)
      localStorage.removeItem(`recon-${sid}-dla-done`)
    }
    localStorage.removeItem(RECON_SESSION_ID_KEY)
    setSessionId(null)
    setSessionState(null)
    if (location.pathname === '/load-files') {
      window.location.reload()
    } else {
      navigate('/load-files')
    }
  }

  return (
    <aside className="fixed left-0 top-0 z-50 h-full w-64 bg-[#98002E]">
      {/* Logo */}
      <div className="relative z-50 flex justify-center pt-6 pb-4 min-h-[4.5rem]">
        <LogoWithMatchedBackground
          background="primary"
          alt="Recon.AI"
          className="h-[6.75rem] w-auto object-contain"
        />
      </div>
      <nav className="flex flex-col gap-1 p-4">
        {navItems.map(({ to, label, icon: Icon }) => {
          const unlocked = isRouteUnlocked(to, sessionState, sessionId)

          if (!unlocked) {
            return (
              <div
                key={to}
                className="flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium cursor-not-allowed select-none"
                style={{ backgroundColor: '#E7E7E7', color: '#000000' }}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="flex-1">{label}</span>
                <Lock className="size-3 shrink-0" aria-hidden />
              </div>
            )
          }

          return (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={to === '/' ? () => window.scrollTo({ top: 0 }) : undefined}
              className="flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium text-white transition-colors bg-[#333333] hover:bg-[#444444]"
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {label}
            </NavLink>
          )
        })}
        <div className="mt-4 border-t border-white/20 pt-4">
          <button
            type="button"
            onClick={handleResetSession}
            className="flex w-full items-center justify-start gap-3 rounded-full bg-[#333333] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#444444]"
          >
            <RotateCcw className="size-4 shrink-0" aria-hidden />
            Restart
          </button>
        </div>
      </nav>
    </aside>
  )
}
