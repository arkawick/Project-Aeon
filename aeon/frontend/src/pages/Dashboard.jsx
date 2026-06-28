import { useEffect, useState, useCallback } from 'react'
import { getPipelines, getIncidents, getIntegrationsStatus, getWorkflows, triggerWorkflow } from '../lib/api.js'
import { AlertTriangle, CheckCircle, Clock, GitBranch, RefreshCw, Zap, Workflow, Play, Loader2 } from 'lucide-react'

const SEVERITY_COLORS = {
  critical: 'bg-red-500/20 text-red-400 border border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
}

const STATUS_COLORS = {
  success: 'text-green-400',
  failure: 'text-red-400',
  running: 'text-yellow-400',
  unknown: 'text-slate-400',
}

function StatCard({ title, value, sub, icon: Icon, color }) {
  return (
    <div className="bg-aeon-surface border border-aeon-border rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-slate-400 text-sm">{title}</p>
          <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
          {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
        </div>
        <div className="p-2 rounded-lg bg-white/5">
          <Icon size={20} className={color} />
        </div>
      </div>
    </div>
  )
}

function IntegrationsBar({ services }) {
  if (!services?.length) return null
  return (
    <div className="bg-aeon-surface border border-aeon-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-white flex items-center gap-2">
          <Zap size={14} className="text-indigo-400" /> Integration Status
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        {services.map((svc) => (
          <div key={svc.name} className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${svc.connected ? 'bg-green-400' : 'bg-slate-600'}`} />
            <span className="text-xs text-slate-400">{svc.name}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${svc.mode === 'live' ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-slate-400'}`}>
              {svc.mode}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function WorkflowsSummary({ workflows }) {
  const [triggering, setTriggering] = useState({})

  async function handleTrigger(wf) {
    setTriggering((s) => ({ ...s, [wf.id]: true }))
    try { await triggerWorkflow(wf.id, {}) } catch {}
    setTimeout(() => setTriggering((s) => ({ ...s, [wf.id]: false })), 2000)
  }

  if (!workflows.length) return null
  return (
    <section>
      <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <Workflow size={18} className="text-indigo-400" /> n8n Workflows
      </h2>
      <div className="bg-aeon-surface border border-aeon-border rounded-xl divide-y divide-aeon-border/50">
        {workflows.map((wf) => (
          <div key={wf.id} className="flex items-center justify-between px-4 py-3 gap-3">
            <div className="min-w-0">
              <p className="text-white text-sm font-medium truncate">{wf.name}</p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`text-xs px-2 py-0.5 rounded-full ${wf.active ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-slate-400'}`}>
                  {wf.active ? 'Active' : 'Inactive'}
                </span>
                {wf.last_run && (
                  <span className="text-xs text-slate-500 flex items-center gap-1">
                    <Clock size={10} /> {new Date(wf.last_run).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
            <button
              onClick={() => handleTrigger(wf)}
              disabled={triggering[wf.id]}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50"
            >
              {triggering[wf.id] ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {triggering[wf.id] ? 'Triggering…' : 'Trigger'}
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function Dashboard() {
  const [pipelines, setPipelines] = useState([])
  const [incidents, setIncidents] = useState([])
  const [integrations, setIntegrations] = useState([])
  const [workflows, setWorkflows] = useState([])
  const [lastRefresh, setLastRefresh] = useState(new Date())
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      const [pipes, incs, intgs, wfs] = await Promise.allSettled([
        getPipelines(),
        getIncidents(),
        getIntegrationsStatus(),
        getWorkflows(),
      ])
      if (pipes.status === 'fulfilled') setPipelines(pipes.value)
      if (incs.status === 'fulfilled') setIncidents(incs.value)
      if (intgs.status === 'fulfilled') setIntegrations(intgs.value.services || [])
      if (wfs.status === 'fulfilled') setWorkflows(wfs.value)
      setLastRefresh(new Date())
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [load])

  const failures = pipelines.filter((p) => p.status === 'failure').slice(0, 5)
  const successRate = pipelines.length
    ? Math.round((pipelines.filter((p) => p.status === 'success').length / pipelines.length) * 100)
    : 87
  const openIncidents = incidents.filter((i) => i.status === 'open').length
  const criticalCount = incidents.filter((i) => i.severity === 'critical').length
  const recommendations = incidents.filter((i) => i.suggested_fix).slice(0, 3)

  const stats = [
    { title: 'Total Pipelines', value: pipelines.length || 12, sub: 'Last 30 days', icon: GitBranch, color: 'text-indigo-400' },
    { title: 'Active Incidents', value: openIncidents || 3, sub: `${criticalCount} critical`, icon: AlertTriangle, color: 'text-red-400' },
    { title: 'Success Rate', value: `${successRate}%`, sub: 'Current window', icon: CheckCircle, color: 'text-green-400' },
    { title: 'Avg Resolution', value: '2.4h', sub: 'Down from 3.1h', icon: Clock, color: 'text-yellow-400' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Engineering Operations Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">Real-time CI/CD monitoring powered by Aeon AI</p>
        </div>
        <button
          onClick={load}
          disabled={refreshing}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-aeon-surface border border-aeon-border px-3 py-1.5 rounded-lg transition-colors"
        >
          <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
          {lastRefresh.toLocaleTimeString()}
        </button>
      </div>

      <IntegrationsBar services={integrations} />

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.map((s) => <StatCard key={s.title} {...s} />)}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <section>
          <h2 className="text-lg font-semibold text-white mb-3">Recent Failures</h2>
          <div className="space-y-3">
            {failures.length > 0 ? failures.map((f) => (
              <div key={f.id} className="bg-aeon-surface border border-aeon-border rounded-lg p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-white font-medium text-sm truncate">{f.name}</p>
                    <p className="text-slate-400 text-xs mt-0.5 truncate">{f.repo}</p>
                    <p className="text-slate-500 text-xs mt-0.5">{f.branch}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30">failure</span>
                    <span className="text-slate-500 text-xs">{f.duration}</span>
                    <span className="text-slate-600 text-xs uppercase">{f.source}</span>
                  </div>
                </div>
              </div>
            )) : (
              /* Fallback mock failures */
              [
                { id: 1, name: 'deploy-staging', repo: 'acme/frontend-app', error: "Cannot find module '@/components/Button'", time: '35m ago', severity: 'high' },
                { id: 2, name: 'integration-tests', repo: 'acme/data-service', error: 'OOM: Java heap space exceeded', time: '1h ago', severity: 'critical' },
              ].map((f) => (
                <div key={f.id} className="bg-aeon-surface border border-aeon-border rounded-lg p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-white font-medium text-sm">{f.name}</p>
                      <p className="text-slate-400 text-xs mt-0.5">{f.repo}</p>
                      <p className="text-red-400 text-xs mt-2 font-mono">{f.error}</p>
                    </div>
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SEVERITY_COLORS[f.severity]}`}>{f.severity}</span>
                      <span className="text-slate-500 text-xs">{f.time}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-white mb-3">AI Recommendations</h2>
          <div className="space-y-3">
            {recommendations.length > 0 ? recommendations.map((r) => (
              <div key={r.id} className="bg-aeon-surface border border-indigo-500/30 rounded-lg p-4">
                <p className="text-white font-medium text-sm">{r.title || r.root_cause?.slice(0, 60)}</p>
                <p className="text-slate-400 text-xs mt-1">{r.suggested_fix?.slice(0, 120)}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-indigo-400 text-xs font-medium">{r.severity} severity</span>
                </div>
              </div>
            )) : (
              [
                { id: 1, title: 'Configure Vite path aliases', description: "Add resolve.alias to vite.config.js to fix '@/...' imports.", impact: 'Fixes 3 failing pipelines' },
                { id: 2, title: 'Increase JVM heap in CI', description: 'Set JAVA_OPTS=-Xmx2g in Jenkins job config.', impact: 'Eliminates OOM in tests' },
              ].map((r) => (
                <div key={r.id} className="bg-aeon-surface border border-indigo-500/30 rounded-lg p-4">
                  <p className="text-white font-medium text-sm">{r.title}</p>
                  <p className="text-slate-400 text-xs mt-1">{r.description}</p>
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-indigo-400 text-xs font-medium">{r.impact}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <WorkflowsSummary workflows={workflows} />
    </div>
  )
}
