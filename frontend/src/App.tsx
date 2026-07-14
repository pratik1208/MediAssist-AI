import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import CampaignAnalyticsPage from './pages/CampaignAnalyticsPage'
import CampaignManagerPage from './pages/CampaignManagerPage'
import CareGapDashboardPage from './pages/CareGapDashboardPage'
import EscalationQueuePage from './pages/EscalationQueuePage'
import FrontdeskChatPage from './pages/FrontdeskChatPage'
import PatientGapPanelPage from './pages/PatientGapPanelPage'
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
import StaffTaskQueuePage from './pages/StaffTaskQueuePage'
import TriageChatPage from './pages/TriageChatPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<FrontdeskChatPage />} />
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
          <Route path="/staff/caregaps" element={<CareGapDashboardPage />} />
          <Route path="/staff/caregaps/patients/:id" element={<PatientGapPanelPage />} />
          <Route path="/staff/frontdesk/tasks" element={<StaffTaskQueuePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
