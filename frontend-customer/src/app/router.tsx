import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from './AppShell'
import { Landing } from './routes/Landing'
import { LoadFiles } from './routes/LoadFiles'
import { Matching } from './routes/Matching'
import { HighLevelAnalysis } from './routes/HighLevelAnalysis'
import { DetailedAnalysisExport } from './routes/DetailedAnalysisExport'
import { Export } from './routes/Export'
import { Documentation } from './routes/Documentation'
import { FAQ } from './routes/FAQ'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Landing /> },
      { path: 'load-files', element: <LoadFiles /> },
      { path: 'matching', element: <Matching /> },
      { path: 'high-level-analysis', element: <HighLevelAnalysis /> },
      { path: 'detailed-analysis', element: <DetailedAnalysisExport /> },
      { path: 'export', element: <Export /> },
      { path: 'documentation', element: <Documentation /> },
      { path: 'faq', element: <FAQ /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
