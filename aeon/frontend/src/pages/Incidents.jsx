import { useEffect, useState, useRef } from 'react'
import { getIncidents, searchIncidents, startOdysseusResearch } from '../lib/api.js'
import { AlertTriangle, Search, ChevronDown, ChevronUp, Clock, Brain, ExternalLink } from 'lucide-react'

const ODYSSEUS_URL = 'http://localhost:7000'

async function openIncidentInOdysseus(query) {
  try {
    const res = await startOdysseusResearch(query)
    window.open(res.odysseus_url || ODYSSEUS_URL, '_blank', 'noopener,noreferrer')
  } catch {
    window.open(ODYSSEUS_URL, '_blank', 'noopener,noreferrer')
  }
}

const SEVERITY_CONFIG = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
}

function SeverityBadge({ severity }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.low}`}>
      {severity}
    </span>
  )
}

function MemoryMatchMini({ match }) {
  if (!match) return null
  const simPct = Math.round((match.similarity || 0) * 100)
  return (
    <div className="mt-2 bg-indigo-950/50 border border-indigo-500/30 rounded-lg px-3 py-2 flex items-center gap-2">
      <Brain size={12} className="text-indigo-400 shrink-0" />
      <span className="text-xs text-indigo-300">Matches <span className="font-mono">{match.id}</span> ({match.time_ago}) · {simPct}% similar</span>
    </div>
  )
}

function IncidentRow({ incident }) {
  const [expanded, setExpanded] = useState(false)
  const isOpen = incident.status === 'open'

  return (
    <div className="bg-aeon-surface border border-aeon-border rounded-xl overflow-hidden">
      <div
        className="flex items-start gap-3 p-4 cursor-pointer hover:bg-white/5 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${isOpen ? 'text-red-400' : 'text-slate-500'}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-white font-medium text-sm">{incident.title || incident.root_cause?.slice(0, 60)}</p>
            <SeverityBadge severity={incident.severity} />
            <span className={`text-xs px-2 py-0.5 rounded-full ${isOpen ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
              {incident.status}
            </span>
          </div>
          <p className="text-slate-400 text-xs mt-1 truncate">{incident.root_cause?.slice(0, 100)}</p>
          {incident.time_ago && (
            <div className="flex items-center gap-1 mt-1">
              <Clock size={10} className="text-slate-500" />
              <span className="text-slate-500 text-xs">{incident.time_ago}</span>
            </div>
          )}
        </div>
        <div className="shrink-0">
          {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 border-t border-aeon-border pt-3 space-y-3">
          <div>
            <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-1">Root Cause</p>
            <p className="text-slate-200 text-sm">{incident.root_cause}</p>
          </div>
          {incident.suggested_fix && (
            <div>
              <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-1">Suggested Fix</p>
              <pre className="text-green-300 text-xs font-mono whitespace-pre-wrap bg-slate-900 rounded-lg p-3">{incident.suggested_fix}</pre>
            </div>
          )}
          {incident.memory_match && <MemoryMatchMini match={incident.memory_match} />}
          <div className="flex items-center gap-3 text-xs text-slate-500 flex-wrap">
            {incident.pipeline_id && <span>Pipeline: <span className="text-slate-400 font-mono">{incident.pipeline_id}</span></span>}
            {incident.error_type && <span>Type: <span className="text-slate-400 font-mono">{incident.error_type}</span></span>}
          </div>
          <button
            onClick={() => openIncidentInOdysseus(incident.root_cause || incident.title || 'DevOps incident')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/60 hover:bg-purple-800/60 border border-purple-500/30 text-purple-300 rounded-lg text-xs transition-colors mt-1"
          >
            <ExternalLink size={11} /> Research in Odysseus
          </button>
        </div>
      )}
    </div>
  )
}

export default function Incidents() {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [severityFilter, setSeverityFilter] = useState('all')
  const debRef = useRef(null)

  useEffect(() => {
    getIncidents().then(setIncidents).catch(() => setIncidents([])).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null)
      return
    }
    clearTimeout(debRef.current)
    debRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await searchIncidents(searchQuery)
        setSearchResults(res)
      } finally {
        setSearching(false)
      }
    }, 400)
  }, [searchQuery])

  const displayed = searchResults
    ? searchResults.matches || []
    : incidents.filter((i) => severityFilter === 'all' || i.severity === severityFilter)

  const openCount = incidents.filter((i) => i.status === 'open').length
  const resolvedCount = incidents.filter((i) => i.status === 'resolved').length
  const criticalCount = incidents.filter((i) => i.severity === 'critical').length

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Incident History</h1>
        <p className="text-slate-400 text-sm mt-1">Memory-backed incident intelligence</p>
      </div>

      {/* Summary */}
      <div className="flex gap-4">
        {[
          { label: 'Open', value: openCount, color: 'text-red-400' },
          { label: 'Resolved', value: resolvedCount, color: 'text-green-400' },
          { label: 'Critical', value: criticalCount, color: 'text-orange-400' },
        ].map((s) => (
          <div key={s.label} className="bg-aeon-surface border border-aeon-border rounded-lg px-4 py-3">
            <p className="text-slate-400 text-xs">{s.label}</p>
            <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Search + filter */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Semantic search: e.g. 'gradle dependency conflict'..."
            className="w-full bg-aeon-surface border border-aeon-border rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
          {searching && <div className="absolute right-3 top-1/2 -translate-y-1/2 w-3 h-3 border border-indigo-500 border-t-transparent rounded-full animate-spin" />}
        </div>
        <div className="flex gap-1 bg-aeon-surface border border-aeon-border rounded-lg p-1">
          {['all', 'critical', 'high', 'medium', 'low'].map((s) => (
            <button
              key={s}
              onClick={() => { setSeverityFilter(s); setSearchQuery('') }}
              className={`px-3 py-1 rounded text-xs capitalize transition-colors ${severityFilter === s && !searchQuery ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {searchResults && (
        <div className="bg-indigo-950/30 border border-indigo-500/20 rounded-lg px-4 py-2 text-xs text-indigo-300">
          {searchResults.summary}
        </div>
      )}

      {loading ? (
        <p className="text-slate-400">Loading incidents...</p>
      ) : displayed.length === 0 ? (
        <p className="text-slate-500 py-8 text-center">No incidents found</p>
      ) : (
        <div className="space-y-3">
          {displayed.map((inc) => (
            <IncidentRow key={inc.id} incident={inc} />
          ))}
        </div>
      )}
    </div>
  )
}
