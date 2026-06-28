import { useEffect, useState, useCallback } from 'react'
import { getPipelines } from '../lib/api.js'
import { GitBranch, RefreshCw, Github, Server, CheckCircle, XCircle, Clock, Loader2, ExternalLink } from 'lucide-react'

const STATUS_CONFIG = {
  success: { label: 'Success', cls: 'bg-green-500/20 text-green-400 border-green-500/30', icon: CheckCircle },
  failure: { label: 'Failure', cls: 'bg-red-500/20 text-red-400 border-red-500/30', icon: XCircle },
  running: { label: 'Running', cls: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30', icon: Loader2 },
  unknown: { label: 'Unknown', cls: 'bg-slate-500/20 text-slate-400 border-slate-500/30', icon: Clock },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.unknown
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${cfg.cls}`}>
      <Icon size={10} className={status === 'running' ? 'animate-spin' : ''} />
      {cfg.label}
    </span>
  )
}

function SourceBadge({ source }) {
  if (source === 'github') return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-400">
      <Github size={11} /> GitHub
    </span>
  )
  if (source === 'jenkins') return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-400">
      <Server size={11} /> Jenkins
    </span>
  )
  return <span className="text-xs text-slate-500">{source}</span>
}

export default function Pipelines() {
  const [pipelines, setPipelines] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('all')
  const [lastRefresh, setLastRefresh] = useState(new Date())
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(async () => {
    setRefreshing(true)
    try {
      const data = await getPipelines()
      setPipelines(data)
      setLastRefresh(new Date())
    } catch {
      setPipelines([])
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [load])

  const filtered = pipelines.filter((p) => {
    if (tab === 'github') return p.source === 'github'
    if (tab === 'jenkins') return p.source === 'jenkins'
    return true
  })

  const tabs = [
    { id: 'all', label: `All (${pipelines.length})` },
    { id: 'github', label: `GitHub (${pipelines.filter(p => p.source === 'github').length})` },
    { id: 'jenkins', label: `Jenkins (${pipelines.filter(p => p.source === 'jenkins').length})` },
  ]

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">CI/CD Pipelines</h1>
          <p className="text-slate-400 text-sm mt-1">Unified view of GitHub Actions + Jenkins</p>
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

      {/* Tabs */}
      <div className="flex gap-1 bg-aeon-surface border border-aeon-border rounded-lg p-1 w-fit">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              tab === t.id ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 py-8">
          <Loader2 size={16} className="animate-spin" />
          <span>Loading pipelines...</span>
        </div>
      ) : (
        <div className="bg-aeon-surface border border-aeon-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-aeon-border">
                <th className="text-left text-slate-400 font-medium px-4 py-3">Pipeline</th>
                <th className="text-left text-slate-400 font-medium px-4 py-3">Repo / Branch</th>
                <th className="text-left text-slate-400 font-medium px-4 py-3">Status</th>
                <th className="text-left text-slate-400 font-medium px-4 py-3">Duration</th>
                <th className="text-left text-slate-400 font-medium px-4 py-3">Source</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-slate-500 py-8">No pipelines found</td>
                </tr>
              ) : filtered.map((p) => (
                <tr key={p.id} className="border-b border-aeon-border/50 hover:bg-white/5 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <GitBranch size={14} className="text-slate-500 shrink-0" />
                      {p.url ? (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-white font-medium hover:text-indigo-400 transition-colors flex items-center gap-1"
                        >
                          {p.name}
                          <ExternalLink size={11} className="text-slate-500" />
                        </a>
                      ) : (
                        <span className="text-white font-medium">{p.name}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-slate-300 text-xs">{p.repo}</p>
                    <p className="text-slate-500 text-xs">{p.branch}</p>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{p.duration || '—'}</td>
                  <td className="px-4 py-3">
                    <SourceBadge source={p.source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
