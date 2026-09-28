import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'

import App from './App.tsx'
import './index.css'
import DemoPage from './pages/DemoPage.tsx'
import EvaluationLabPage from './pages/EvaluationLabPage.tsx'
import EvolutionTimelinePage from './pages/EvolutionTimelinePage.tsx'
import HomePage from './pages/HomePage.tsx'
import SkillStudioEntry from './pages/SkillStudioEntry.tsx'
import SkillStudioPage from './pages/SkillStudioPage.tsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<HomePage />} />
            <Route path="demo" element={<DemoPage />} />
            <Route path="skills" element={<SkillStudioEntry />} />
            <Route
              path="skills/:id/evaluations"
              element={<EvaluationLabPage />}
            />
            <Route
              path="skills/:id/timeline"
              element={<EvolutionTimelinePage />}
            />
            <Route path="skills/:id" element={<SkillStudioPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
