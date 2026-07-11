import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import EscalationQueuePage from './pages/EscalationQueuePage'
import RefillQueuePage from './pages/RefillQueuePage'
import RefillsPage from './pages/RefillsPage'
import RegistrationChatPage from './pages/RegistrationChatPage'
import SchedulingChatPage from './pages/SchedulingChatPage'
import TriageChatPage from './pages/TriageChatPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/schedule" replace />} />
          <Route path="/schedule" element={<SchedulingChatPage />} />
          <Route path="/register" element={<RegistrationChatPage />} />
          <Route path="/triage" element={<TriageChatPage />} />
          <Route path="/refills" element={<RefillsPage />} />
          <Route path="/staff/escalations" element={<EscalationQueuePage />} />
          <Route path="/staff/refills" element={<RefillQueuePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
