import { useState, useRef, useCallback, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { streamBlastRadius } from '../lib/api.js'
import {
  Zap, Loader2, AlertCircle, X, ChevronRight,
  GitPullRequest, FileCode, Server, TestTube, Settings,
  GitBranch, Package, HardDrive, FileText, Info,
  AlertTriangle, CheckCircle, ShieldAlert, Brain,
} from 'lucide-react'

const NODE_META = {
  PR:             { icon: GitPullRequest, label: 'Pull Request' },
  File:           { icon: FileCode,       label: 'Changed File' },
  Service:        { icon: Server,         label: 'Service' },
  Test:           { icon: TestTube,       label: 'Tests' },
  Config:         { icon: Settings,       label: 'Config' },
  Pipeline:       { icon: GitBranch,      label: 'Pipeline' },
  Infrastructure: { icon: HardDrive,      label: 'Infrastructure' },
  Dependencies:   { icon: Package,        label: 'Dependencies' },
  Docs:           { icon: FileText,       label: 'Docs' },
  Incident:       { icon: Brain,          label: 'Past Incident' },
}

const NODE_COLORS = {
  PR:             '#22c55e',
  File:           '#64748b',
  Service:        '#f97316',
  Test:           '#a855f7',
  Config:         '#eab308',
  Pipeline:       '#3b82f6',
  Infrastructure: '#ec4899',
  Dependencies:   '#ef4444',
  Docs:           '#94a3b8',
  Incident:       '#9cdef2',
}

const RISK_STYLES = {
  HIGH:    { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-400',    icon: ShieldAlert },
  MEDIUM:  { bg: 'bg-amber-500/10',  border: 'border-amber-500/30',  text: 'text-amber-400',  icon: AlertTriangle },
  LOW:     { bg: 'bg-green-500/10',  border: 'border-green-500/30',  text: 'text-green-400',  icon: CheckCircle },
  UNKNOWN: { bg: 'bg-slate-500/10',  border: 'border-slate-500/30',  text: 'text-slate-400',  icon: Info },
}

const EXAMPLE_REPOS = [
  'expressjs/express',
  'pallets/flask',
  'psf/requests',
  'django/django',
]

// ── Radial layout: PR center → Files ring → Impact outer ring ─────────────
function computeRadialLayout(nodes) {
  const prNode     = nodes.find(n => n.type === 'PR')
  const fileNodes  = nodes.filter(n => n.type === 'File')
  const impactNodes = nodes.filter(n => n.type !== 'PR' && n.type !== 'File')

  const pos = {}
  if (prNode) pos[prNode.id] = { fx: 0, fy: 0, x: 0, y: 0 }

  const fileR = Math.max(130, fileNodes.length * 22)
  fileNodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / fileNodes.length - Math.PI / 2
    pos[n.id] = { fx: Math.cos(angle) * fileR, fy: Math.sin(angle) * fileR }
    pos[n.id].x = pos[n.id].fx
    pos[n.id].y = pos[n.id].fy
  })

  const impactR = fileR + 130
  impactNodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / impactNodes.length - Math.PI / 2
    pos[n.id] = { fx: Math.cos(angle) * impactR, fy: Math.sin(angle) * impactR }
    pos[n.id].x = pos[n.id].fx
    pos[n.id].y = pos[n.id].fy
  })

  return pos
}

// ─────────────────────────────────────────────────────────────────────────
export default function BlastRadius() {
  const [repo, setRepo]     = useState('')
  const [pr, setPr]         = useState('')
  const [status, setStatus] = useState('idle')
  const [steps, setSteps]   = useState([])
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [meta, setMeta]     = useState(null)
  const [risk, setRisk]     = useState(null)
  const [memory, setMemory] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError]   = useState('')
  const [layout, setLayout] = useState('radial')

  const esRef        = useRef(null)
  const graphRef     = useRef(null)
  const originalGraph = useRef({ nodes: [], links: [] })

  const abort = useCallback(() => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
  }, [])
  useEffect(() => () => abort(), [abort])

  const applyLayout = useCallback((mode, orig) => {
    if (!orig.nodes.length) return
    const freshNodes = orig.nodes.map(n => ({ ...n }))
    const freshLinks = orig.links.map(l => ({ ...l }))

    if (mode === 'radial') {
      const pos = computeRadialLayout(freshNodes)
      setGraphData({
        nodes: freshNodes.map(n => ({ ...n, ...(pos[n.id] || {}) })),
        links: freshLinks,
      })
    } else {
      setGraphData({ nodes: freshNodes, links: freshLinks })
    }
  }, [])

  function analyze() {
    const prNum = parseInt(pr)
    if (!repo.trim() || !prNum) return
    abort()
    setStatus('loading')
    setSteps([])
    setGraphData({ nodes: [], links: [] })
    originalGraph.current = { nodes: [], links: [] }
    setMeta(null)
    setRisk(null)
    setMemory(null)
    setSelected(null)
    setError('')

    const es = streamBlastRadius(repo.trim(), prNum)
    esRef.current = es

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      if (event.type === 'step') {
        setSteps(prev => [...prev, event.message])
      } else if (event.type === 'risk') {
        setRisk(event)
      } else if (event.type === 'memory') {
        setMemory(event.matches)
      } else if (event.type === 'result') {
        const orig = { nodes: event.nodes, links: event.edges }
        originalGraph.current = orig
        applyLayout(layout, orig)
        setMeta(event.meta)
        setStatus('done')
        es.close()
      } else if (event.type === 'error') {
        setError(event.message)
        setStatus('error')
        es.close()
      }
    }
    es.onerror = () => {
      setError('Connection lost. Is Aeon running?')
      setStatus('error')
      es.close()
    }
  }

  function switchLayout(mode) {
    setLayout(mode)
    applyLayout(mode, originalGraph.current)
  }

  const paintNode = useCallback((node, ctx, globalScale) => {
    const isSelected = selected?.id === node.id
    const color = node.color || '#64748b'
    const size = node.type === 'PR' ? 12 : node.type === 'File' ? 7 : 9

    if (node.type === 'PR') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, size + 8, 0, 2 * Math.PI)
      ctx.fillStyle = `${color}15`
      ctx.fill()
    }

    ctx.beginPath()
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
    ctx.fillStyle = isSelected ? '#ffffff' : color
    ctx.fill()
    ctx.strokeStyle = isSelected ? color : `${color}88`
    ctx.lineWidth   = isSelected ? 2.5 : 1.5
    ctx.stroke()

    if (globalScale >= 0.9 || node.type === 'PR') {
      const label = node.label || node.id
      const fs = Math.max(10 / globalScale, 4.5)
      ctx.font      = `${node.type === 'PR' ? 700 : 400} ${fs}px "Fira Code", monospace`
      ctx.fillStyle = isSelected ? color : '#cbd5e1'
      ctx.textAlign = 'center'
      ctx.fillText(label, node.x, node.y + size + fs + 1)
    }
  }, [selected])

  const riskStyle = RISK_STYLES[risk?.risk_level || 'UNKNOWN']
  const RiskIcon  = riskStyle.icon

  return (
    <div className="flex h-full">

      {/* ── Left panel ──────────────────────────────────────────────── */}
      <div className="w-72 shrink-0 flex flex-col border-r border-aeon-border bg-aeon-surface">
        <div className="flex-1 overflow-y-auto flex flex-col">

          {/* Header */}
          <div className="p-4 border-b border-aeon-border">
            <div className="flex items-center gap-2 mb-1">
              <Zap size={16} className="text-orange-400" />
              <h2 className="text-white font-semibold text-sm">Blast Radius</h2>
            </div>
            <p className="text-slate-500 text-xs leading-relaxed">
              Paste a PR — see exactly which services, tests, and pipelines it touches before you merge.
            </p>
          </div>

          {/* Inputs */}
          <div className="p-4 space-y-3 border-b border-aeon-border">
            <div>
              <label className="block text-xs text-slate-400 mb-1">GitHub Repo</label>
              <input
                value={repo}
                onChange={e => setRepo(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && analyze()}
                placeholder="expressjs/express"
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-orange-400 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">PR Number</label>
              <input
                value={pr}
                onChange={e => setPr(e.target.value.replace(/\D/g, ''))}
                onKeyDown={e => e.key === 'Enter' && analyze()}
                placeholder="1234"
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-orange-400 font-mono"
              />
            </div>
            <button
              onClick={analyze}
              disabled={status === 'loading' || !repo.trim() || !pr}
              className="w-full flex items-center justify-center gap-2 bg-orange-400/10 hover:bg-orange-400/20 border border-orange-400/30 text-orange-400 rounded-lg px-4 py-2 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {status === 'loading'
                ? <><Loader2 size={13} className="animate-spin" /> Analyzing…</>
                : <><Zap size={13} /> Analyze Blast Radius</>}
            </button>
          </div>

          {/* How to find a PR */}
          <div className="p-3 border-b border-aeon-border">
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-2">How to find a PR</p>
            <p className="text-xs text-slate-500 leading-relaxed mb-2">
              Go to any public repo's <span className="text-slate-300 font-mono">Pull Requests</span> tab and copy the number from the URL or title.
            </p>
            <p className="text-xs text-slate-600 font-mono mb-2">github.com/owner/repo/pull/<span className="text-orange-400">1234</span></p>
            <p className="text-xs text-slate-500 mb-1.5">Try these repos:</p>
            {EXAMPLE_REPOS.map(r => (
              <button key={r} onClick={() => setRepo(r)}
                className="w-full text-left flex items-center gap-2 px-2 py-1 rounded text-xs hover:bg-white/5 transition-colors">
                <ChevronRight size={9} className="text-slate-600 shrink-0" />
                <span className="text-slate-400 font-mono">{r}</span>
              </button>
            ))}
          </div>

          {/* Progress */}
          {steps.length > 0 && (
            <div className="p-3 border-b border-aeon-border">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Progress</p>
              <div className="space-y-1">
                {steps.map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <div className="w-1 h-1 rounded-full bg-orange-400 mt-1.5 shrink-0" />
                    <span className="text-slate-400 leading-relaxed">{s}</span>
                  </div>
                ))}
                {status === 'loading' && (
                  <div className="flex items-center gap-1.5 text-xs text-slate-600 mt-1">
                    <Loader2 size={9} className="animate-spin" /> Working…
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Stats */}
          {meta && (
            <div className="p-3 border-b border-aeon-border">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-2">PR Stats</p>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                <div className="bg-aeon-dark rounded-lg p-2 text-center">
                  <div className="text-base font-bold font-mono text-white">{meta.total_files}</div>
                  <div className="text-xs text-slate-600">files</div>
                </div>
                <div className="bg-aeon-dark rounded-lg p-2 text-center">
                  <div className="text-base font-bold font-mono">
                    <span className="text-green-400">+{meta.additions}</span>
                    {' '}
                    <span className="text-red-400">-{meta.deletions}</span>
                  </div>
                  <div className="text-xs text-slate-600">lines</div>
                </div>
              </div>
              {/* Impact breakdown */}
              <div className="space-y-1">
                {Object.entries(meta.impacts || {}).map(([cat, count]) => (
                  <div key={cat} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: NODE_COLORS[cat] || '#64748b' }} />
                      <span className="text-slate-400">{cat}</span>
                    </span>
                    <span className="text-slate-500 font-mono">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error */}
          {status === 'error' && (
            <div className="p-3">
              <div className="flex items-start gap-2 p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg">
                <AlertCircle size={13} className="text-red-400 mt-0.5 shrink-0" />
                <p className="text-xs text-red-300 break-words min-w-0">{error}</p>
              </div>
            </div>
          )}

          {/* Legend */}
          <div className="p-3 border-t border-aeon-border mt-auto">
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Legend</p>
            <div className="space-y-1">
              {Object.entries(NODE_META).map(([type, { icon: Icon, label }]) => (
                <div key={type} className="flex items-center gap-2 text-xs text-slate-500">
                  <Icon size={11} style={{ color: NODE_COLORS[type] }} />
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Main area ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* ── AI Risk banner ──────────────────────────────────────── */}
        {risk && risk.risk_level !== 'UNKNOWN' && (
          <div className={`shrink-0 border-b border-aeon-border px-5 py-3 ${riskStyle.bg}`}>
            <div className="flex items-start gap-3">
              <div className={`shrink-0 mt-0.5 w-6 h-6 rounded-lg border flex items-center justify-center ${riskStyle.bg} ${riskStyle.border}`}>
                <RiskIcon size={12} className={riskStyle.text} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-bold uppercase tracking-wide ${riskStyle.text}`}>
                    {risk.risk_level} RISK
                  </span>
                  {risk.deploy_recommendation && (
                    <span className="text-xs text-slate-400">· {risk.deploy_recommendation}</span>
                  )}
                </div>
                {risk.narrative && (
                  <p className="text-sm text-slate-300 leading-relaxed">{risk.narrative}</p>
                )}
                {risk.must_test?.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {risk.must_test.map((t, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 rounded bg-white/5 border border-white/10 text-slate-400">
                        ✓ {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Incident Memory banner ──────────────────────────────── */}
        {memory && memory.length > 0 && (
          <div className="shrink-0 border-b border-aeon-border px-5 py-3 bg-cyan-400/5">
            <div className="flex items-start gap-3">
              <div className="shrink-0 mt-0.5 w-6 h-6 rounded-lg border border-cyan-400/30 bg-cyan-400/10 flex items-center justify-center">
                <Brain size={12} className="text-cyan-300" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-bold uppercase tracking-wide text-cyan-300">Incident Memory</span>
                  <span className="text-xs text-slate-400">
                    · {memory.length} related past incident{memory.length > 1 ? 's' : ''} recalled
                  </span>
                </div>
                <div className="space-y-1.5">
                  {memory.map((m, i) => (
                    <div key={m.incident_id || i} className="text-xs text-slate-300 leading-relaxed">
                      <span className="font-mono text-cyan-300">{m.incident_id}</span>
                      <span className="text-slate-500"> · {Math.round((m.similarity || 0) * 100)}% match</span>
                      {m.matched_files?.length > 0 && (
                        <span className="text-slate-500">
                          {' '}· touches <span className="font-mono text-slate-400">{m.matched_files.join(', ')}</span>
                        </span>
                      )}
                      {m.root_cause && <span className="text-slate-400"> — {m.root_cause}</span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Graph toolbar ───────────────────────────────────────── */}
        {graphData.nodes.length > 0 && (
          <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-aeon-border bg-aeon-surface">
            <span className="text-xs text-slate-500 mr-1">Layout:</span>
            {[
              { mode: 'radial', label: 'Radial' },
              { mode: 'force',  label: 'Force' },
            ].map(({ mode, label }) => (
              <button key={mode} onClick={() => switchLayout(mode)}
                className={['flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium border transition-colors',
                  layout === mode
                    ? 'bg-orange-400/10 border-orange-400 text-orange-400'
                    : 'border-aeon-border text-slate-500 hover:text-slate-300',
                ].join(' ')}>
                {label}
              </button>
            ))}
            {meta?.pr_url && (
              <a href={meta.pr_url} target="_blank" rel="noopener noreferrer"
                className="ml-auto text-xs text-slate-500 hover:text-white transition-colors">
                View on GitHub ↗
              </a>
            )}
          </div>
        )}

        {/* ── Graph canvas ────────────────────────────────────────── */}
        <div className="flex-1 relative bg-aeon-dark overflow-hidden">
          {status === 'idle' && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Zap size={44} className="text-slate-700 mx-auto" />
                <p className="text-slate-500 text-sm">Enter a public GitHub repo and PR number</p>
                <p className="text-slate-600 text-xs">Click an example on the left to start</p>
              </div>
            </div>
          )}

          {status === 'loading' && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Loader2 size={30} className="text-orange-400 mx-auto animate-spin" />
                <p className="text-slate-400 text-sm">Mapping blast radius…</p>
              </div>
            </div>
          )}

          {graphData.nodes.length > 0 && (
            <ForceGraph2D
              key={layout}
              ref={graphRef}
              graphData={graphData}
              nodeCanvasObject={paintNode}
              nodeCanvasObjectMode={() => 'replace'}
              onNodeClick={node => setSelected(selected?.id === node.id ? null : node)}
              linkColor={l => l.type === 'IMPACTS' ? '#f9741633' : l.type === 'RECALLS' ? '#9cdef255' : '#33415566'}
              linkWidth={l => l.type === 'IMPACTS' ? 1.5 : l.type === 'RECALLS' ? 1.5 : 1}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              linkLabel={l => l.type}
              backgroundColor="#1e2430"
              cooldownTicks={layout === 'radial' ? 0 : 80}
            />
          )}

          {/* ── Node detail panel ─────────────────────────────────── */}
          {selected && (
            <div className="absolute top-3 right-3 w-72 bg-aeon-surface border border-aeon-border rounded-xl shadow-2xl overflow-hidden">
              <div className="px-4 py-3 flex items-center justify-between border-b border-aeon-border"
                style={{ borderLeftColor: selected.color, borderLeftWidth: 3 }}>
                <div className="flex items-center gap-2">
                  {(() => { const M = NODE_META[selected.type]; return M ? <M.icon size={13} style={{ color: selected.color }} /> : null })()}
                  <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
                    {NODE_META[selected.type]?.label || selected.type}
                  </span>
                </div>
                <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white transition-colors">
                  <X size={13} />
                </button>
              </div>

              <div className="p-4 space-y-3">
                <p className="text-white font-semibold text-sm">{selected.label}</p>

                {selected.risk && (
                  <span className={`inline-block text-xs px-2 py-0.5 rounded font-semibold uppercase ${RISK_STYLES[selected.risk]?.text || 'text-slate-400'} ${RISK_STYLES[selected.risk]?.bg || ''} border ${RISK_STYLES[selected.risk]?.border || ''}`}>
                    {selected.risk} RISK
                  </span>
                )}

                <div className="space-y-1.5 text-xs">
                  {selected.full_path && (
                    <div>
                      <span className="text-slate-500 block mb-0.5">Path</span>
                      <p className="text-slate-300 font-mono break-all">{selected.full_path}</p>
                    </div>
                  )}
                  {selected.category && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Category</span>
                      <span className="text-slate-300">{selected.category}</span>
                    </div>
                  )}
                  {(selected.additions !== undefined) && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Changes</span>
                      <span>
                        <span className="text-green-400">+{selected.additions}</span>
                        {' '}
                        <span className="text-red-400">-{selected.deletions}</span>
                      </span>
                    </div>
                  )}
                  {selected.status && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Status</span>
                      <span className="text-slate-300">{selected.status}</span>
                    </div>
                  )}
                  {selected.file_count > 0 && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Files touching this</span>
                      <span className="text-slate-300 font-mono">{selected.file_count}</span>
                    </div>
                  )}
                  {selected.title && (
                    <div>
                      <span className="text-slate-500 block mb-0.5">Title</span>
                      <p className="text-slate-300 leading-relaxed">{selected.title}</p>
                    </div>
                  )}
                  {selected.author && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Author</span>
                      <span className="text-slate-300">{selected.author}</span>
                    </div>
                  )}
                  {selected.similarity !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Memory match</span>
                      <span className="text-cyan-300 font-mono">{Math.round(selected.similarity * 100)}%</span>
                    </div>
                  )}
                  {selected.matched_files?.length > 0 && (
                    <div>
                      <span className="text-slate-500 block mb-0.5">Shared files</span>
                      <p className="text-slate-300 font-mono break-all">{selected.matched_files.join(', ')}</p>
                    </div>
                  )}
                  {selected.root_cause && (
                    <div>
                      <span className="text-slate-500 block mb-0.5">Past root cause</span>
                      <p className="text-slate-300 leading-relaxed">{selected.root_cause}</p>
                    </div>
                  )}
                  {selected.fix && (
                    <div>
                      <span className="text-slate-500 block mb-0.5">Past fix</span>
                      <p className="text-slate-300 leading-relaxed">{selected.fix}</p>
                    </div>
                  )}
                </div>

                {selected.url && (
                  <a href={selected.url} target="_blank" rel="noopener noreferrer"
                    className="block text-center py-1.5 rounded-lg border border-aeon-border text-slate-400 hover:text-white hover:border-orange-400 transition-colors text-xs">
                    View on GitHub ↗
                  </a>
                )}
              </div>
            </div>
          )}

          {status === 'done' && !selected && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-aeon-surface/90 border border-aeon-border rounded-lg px-4 py-2 pointer-events-none">
              <p className="text-xs text-slate-400">Click any node for details · orange edges show impact paths</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
