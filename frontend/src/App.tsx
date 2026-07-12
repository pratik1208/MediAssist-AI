import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import CampaignAnalyticsPage from './pages/CampaignAnalyticsPage'
import CampaignManagerPage from './pages/CampaignManagerPage'
import EscalationQueuePage from './pages/EscalationQueuePage'
import PatientAuthorizationsPage from './pages/PatientAuthorizationsPage'
import PatientReferralsPage from './pages/PatientReferralsPage'
import PriorAuthDetailPage from './pages/PriorAuthDetailPage'
import PriorAuthQueuePage from './pages/PriorAuthQueuePage'
import PriorAuthTasksPage from './pages/PriorAuthTasksPage'
import ReferralDashboardPage from './pages/ReferralDashboardPage'
import ReferralDetailPage from './pages/ReferralDetailPage'
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
          <Route path="/referrals" element={<PatientReferralsPage />} />
          <Route path="/authorizations" element={<PatientAuthorizationsPage />} />
          <Route path="/staff/escalations" element={<EscalationQueuePage />} />
          <Route path="/staff/refills" element={<RefillQueuePage />} />
          <Route path="/staff/referrals" element={<ReferralDashboardPage />} />
          <Route path="/staff/referrals/:id" element={<ReferralDetailPage />} />
          <Route path="/staff/priorauth" element={<PriorAuthQueuePage />} />
          <Route path="/staff/priorauth/tasks" element={<PriorAuthTasksPage />} />
          <Route path="/staff/priorauth/:id" element={<PriorAuthDetailPage />} />
          <Route path="/staff/outreach" element={<CampaignManagerPage />} />
          <Route path="/staff/outreach/:id" element={<CampaignAnalyticsPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
