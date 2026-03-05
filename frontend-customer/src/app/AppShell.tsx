import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'

export function AppShell() {
  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <main className="min-h-screen pt-16 pl-0 md:pl-64 md:pt-0">
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
