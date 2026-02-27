import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from '@/pages/LandingPage'
import SessionDashboard from '@/pages/SessionDashboard'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/sessions/:sessionId" element={<SessionDashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
