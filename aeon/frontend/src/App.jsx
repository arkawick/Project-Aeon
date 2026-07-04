import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import AIAssistant from './pages/AIAssistant.jsx'
import Pipelines from './pages/Pipelines.jsx'
import Incidents from './pages/Incidents.jsx'
import Workflows from './pages/Workflows.jsx'
import GraphView from './pages/GraphView.jsx'
import Provenance from './pages/Provenance.jsx'
import BlastRadius from './pages/BlastRadius.jsx'
import CoChange from './pages/CoChange.jsx'

function Layout({ children }) {
  return (
    <div className="flex h-screen bg-aeon-dark overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        {children}
      </main>
    </div>
  )
}

function FullLayout({ children }) {
  return (
    <div className="flex h-screen bg-aeon-dark overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout><Dashboard /></Layout>} />
        <Route path="/ai" element={<Layout><AIAssistant /></Layout>} />
        <Route path="/pipelines" element={<Layout><Pipelines /></Layout>} />
        <Route path="/incidents" element={<Layout><Incidents /></Layout>} />
        <Route path="/workflows" element={<Layout><Workflows /></Layout>} />
        <Route path="/graph" element={<FullLayout><GraphView /></FullLayout>} />
        <Route path="/provenance" element={<FullLayout><Provenance /></FullLayout>} />
        <Route path="/blast" element={<FullLayout><BlastRadius /></FullLayout>} />
        <Route path="/cochange" element={<FullLayout><CoChange /></FullLayout>} />
      </Routes>
    </BrowserRouter>
  )
}
