import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import AIAssistant from './pages/AIAssistant.jsx'
import Pipelines from './pages/Pipelines.jsx'
import Incidents from './pages/Incidents.jsx'
import Workflows from './pages/Workflows.jsx'
import GraphView from './pages/GraphView.jsx'

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

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ai" element={<AIAssistant />} />
          <Route path="/pipelines" element={<Pipelines />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/workflows" element={<Workflows />} />
          <Route path="/graph" element={<GraphView />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
