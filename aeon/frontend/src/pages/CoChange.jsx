import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { streamCoChange } from '../lib/api.js'
import {
  Link2, Loader2, AlertCircle, X, ChevronRight,
  FileCode, Sparkles, Info,
} from 'lucide-react'

const EXAMPLE_REPOS = [
  'expressjs/express',
  'pallets/flask',
  'psf/requests',
  'tiangolo/fastapi',
]

const DEPTH_OPTIONS = [
  { value: 50,  label: '50 commits — fast' },
  { value: 100, label: '100 commits — balanced' },
  { value: 200, label: '200 commits — thorough' },
]

function scoreColor(score) {
  if (score >= 0.7) return '#ef4444'
  if (score >= 0.4) return '#f59e0b'
  return '#64748b'
}

export default function CoChange() {
  const [repo, setRepo]         = useState('')
  const [depth, setDepth]       = useState(100)
  const [focusFile, setFocusFile] = useState('')
  const [status, setStatus]     = useState('idle')
  const [steps, setSteps]       = useState([])
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [meta, setMeta]         = useState(null)
  const [insight, setInsight]   = useState('')
  const [selected, setSelected] = useState(null)
  const [error, setError]       = useState('')

  const esRef = useRef(null)

  const abort = useCallback(() => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
  }, [])
  useEffect(() => () => abort(), [abort])

  function analyze() {
    if (!repo.trim()) return
    abort()
    setStatus('loading')
    setSteps([])
    setGraphData({ nodes: [], links: [] })
    setMeta(null)
    setInsight('')
    setSelected(null)
    setError('')

    const es = streamCoChange(repo.trim(), depth, focusFile.trim())
    esRef.current = es

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      if (event.type === 'step') {
        setSteps(prev => [...prev, event.message])
      } else if (event.type === 'insight') {
        setInsight(event.text)
      } else if (event.type === 'result') {
        setGraphData({ nodes: event.nodes, links: event.edges })
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

  // Coupling partners of the selected file, strongest first
  const partners = useMemo(() => {
    if (!selected) return []
    return graphData.links
      .filter(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        return s === selected.id || t === selected.id
      })
      .map(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source
        const t = typeof l.target === 'object' ? l.target.id : l.target
        return { other: s === selected.id ? t : s, co_count: l.co_count, score: l.score }
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 10)
  }, [selected, graphData])

  const paintNode = useCallback((node, ctx, globalScale) => {
    const isSelected = selected?.id === node.id
    const size = Math.min(4 + Math.sqrt(node.changes || 1) * 1.6, 14)

    ctx.beginPath()
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
    ctx.fillStyle = isSelected ? '#ffffff' : node.color || '#64748b'
    ctx.fill()
    ctx.strokeStyle = isSelected ? (node.color || '#64748b') : `${node.color || '#64748b'}88`
    ctx.lineWidth = isSelected ? 2.5 : 1.5
    ctx.stroke()

    if (globalScale >= 1 || isSelected) {
      const fs = Math.max(10 / globalScale, 4.5)
      ctx.font = `400 ${fs}px "Fira Code", monospace`
      ctx.fillStyle = isSelected ? (node.color || '#cbd5e1') : '#cbd5e1'
      ctx.textAlign = 'center'
      ctx.fillText(node.label || node.id, node.x, node.y + size + fs + 1)
    }
  }, [selected])

  return (
    <div className="flex h-full">

      {/* ── Left panel ──────────────────────────────────────────────── */}
      <div className="w-72 shrink-0 flex flex-col border-r border-aeon-border bg-aeon-surface">
        <div className="flex-1 overflow-y-auto flex flex-col">

          {/* Header */}
          <div className="p-4 border-b border-aeon-border">
            <div className="flex items-center gap-2 mb-1">
              <Link2 size={16} className="text-teal-400" />
              <h2 className="text-white font-semibold text-sm">Co-Change Coupling</h2>
            </div>
            <p className="text-slate-500 text-xs leading-relaxed">
              Files that change together, break together. Mines commit history for hidden coupling no import graph shows.
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
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-teal-400 font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">History depth</label>
              <select
                value={depth}
                onChange={e => setDepth(parseInt(e.target.value))}
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-teal-400"
              >
                {DEPTH_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Focus file <span className="text-slate-600">(optional)</span>
              </label>
              <input
                value={focusFile}
                onChange={e => setFocusFile(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && analyze()}
                placeholder="lib/response.js"
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-teal-400 font-mono"
              />
            </div>
            <button
              onClick={analyze}
              disabled={status === 'loading' || !repo.trim()}
              className="w-full flex items-center justify-center gap-2 bg-teal-400/10 hover:bg-teal-400/20 border border-teal-400/30 text-teal-300 rounded-lg px-4 py-2 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {status === 'loading'
                ? <><Loader2 size={13} className="animate-spin" /> Mining history…</>
                : <><Link2 size={13} /> Analyze Coupling</>}
            </button>
          </div>

          {/* Examples */}
          <div className="p-3 border-b border-aeon-border">
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-2">Try these repos</p>
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
                    <div className="w-1 h-1 rounded-full bg-teal-400 mt-1.5 shrink-0" />
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

          {/* Stats + top pairs */}
          {meta && (
            <div className="p-3 border-b border-aeon-border">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-2">Analysis</p>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                <div className="bg-aeon-dark rounded-lg p-2 text-center">
                  <div className="text-base font-bold font-mono text-white">{meta.commits_analyzed}</div>
                  <div className="text-xs text-slate-600">commits</div>
                </div>
                <div className="bg-aeon-dark rounded-lg p-2 text-center">
                  <div className="text-base font-bold font-mono text-white">{meta.pairs_found}</div>
                  <div className="text-xs text-slate-600">coupled pairs</div>
                </div>
              </div>
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Strongest couplings</p>
              <div className="space-y-1.5">
                {(meta.top_pairs || []).map((p, i) => (
                  <div key={i} className="text-xs">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-slate-400 font-mono truncate mr-2">
                        {p.a.split('/').pop()} ↔ {p.b.split('/').pop()}
                      </span>
                      <span className="text-slate-500 font-mono shrink-0">{p.co_count}×</span>
                    </div>
                    <div className="h-1 rounded bg-white/5 overflow-hidden">
                      <div className="h-full rounded" style={{ width: `${Math.round(p.score * 100)}%`, background: scoreColor(p.score) }} />
                    </div>
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
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Edge strength</p>
            <div className="space-y-1">
              {[
                { color: '#ef4444', label: '≥ 70% — tight coupling' },
                { color: '#f59e0b', label: '40–70% — moderate' },
                { color: '#64748b', label: '< 40% — loose' },
              ].map(({ color, label }) => (
                <div key={label} className="flex items-center gap-2 text-xs text-slate-500">
                  <span className="w-4 h-0.5 rounded shrink-0" style={{ background: color }} />
                  <span>{label}</span>
                </div>
              ))}
              <div className="flex items-center gap-2 text-xs text-slate-500 pt-1">
                <Info size={11} className="shrink-0" />
                <span>Node size = how often the file changes</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Main area ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* AI insight banner */}
        {insight && (
          <div className="shrink-0 border-b border-aeon-border px-5 py-3 bg-teal-400/5">
            <div className="flex items-start gap-3">
              <div className="shrink-0 mt-0.5 w-6 h-6 rounded-lg border border-teal-400/30 bg-teal-400/10 flex items-center justify-center">
                <Sparkles size={12} className="text-teal-300" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="block text-xs font-bold uppercase tracking-wide text-teal-300 mb-1">AI Coupling Insight</span>
                <p className="text-sm text-slate-300 leading-relaxed">{insight}</p>
              </div>
            </div>
          </div>
        )}

        {/* Toolbar */}
        {graphData.nodes.length > 0 && (
          <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-aeon-border bg-aeon-surface">
            <span className="text-xs text-slate-500">
              {graphData.nodes.length} files · {graphData.links.length} couplings
              {meta?.focus && <> · focused on <span className="font-mono text-teal-300">{meta.focus}</span></>}
            </span>
            {meta?.repo && (
              <a href={`https://github.com/${meta.repo}`} target="_blank" rel="noopener noreferrer"
                className="ml-auto text-xs text-slate-500 hover:text-white transition-colors">
                View on GitHub ↗
              </a>
            )}
          </div>
        )}

        {/* Graph canvas */}
        <div className="flex-1 relative bg-aeon-dark overflow-hidden">
          {status === 'idle' && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Link2 size={44} className="text-slate-700 mx-auto" />
                <p className="text-slate-500 text-sm">Enter a public GitHub repo to mine its change history</p>
                <p className="text-slate-600 text-xs">Files that repeatedly change in the same commit are coupled</p>
              </div>
            </div>
          )}

          {status === 'loading' && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Loader2 size={30} className="text-teal-400 mx-auto animate-spin" />
                <p className="text-slate-400 text-sm">Mining co-change patterns…</p>
              </div>
            </div>
          )}

          {graphData.nodes.length > 0 && (
            <ForceGraph2D
              graphData={graphData}
              nodeCanvasObject={paintNode}
              nodeCanvasObjectMode={() => 'replace'}
              onNodeClick={node => setSelected(selected?.id === node.id ? null : node)}
              linkColor={l => `${scoreColor(l.score || 0)}66`}
              linkWidth={l => 1 + (l.score || 0) * 3}
              linkLabel={l => `${l.co_count}× together · ${Math.round((l.score || 0) * 100)}% coupled`}
              backgroundColor="#1e2430"
              cooldownTicks={90}
            />
          )}

          {/* Node detail panel */}
          {selected && (
            <div className="absolute top-3 right-3 w-72 bg-aeon-surface border border-aeon-border rounded-xl shadow-2xl overflow-hidden">
              <div className="px-4 py-3 flex items-center justify-between border-b border-aeon-border"
                style={{ borderLeftColor: selected.color, borderLeftWidth: 3 }}>
                <div className="flex items-center gap-2">
                  <FileCode size={13} style={{ color: selected.color }} />
                  <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">File</span>
                </div>
                <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white transition-colors">
                  <X size={13} />
                </button>
              </div>

              <div className="p-4 space-y-3">
                <p className="text-white font-semibold text-sm break-all">{selected.label}</p>
                <div className="space-y-1.5 text-xs">
                  <div>
                    <span className="text-slate-500 block mb-0.5">Path</span>
                    <p className="text-slate-300 font-mono break-all">{selected.full_path}</p>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Changes in window</span>
                    <span className="text-slate-300 font-mono">{selected.changes}</span>
                  </div>
                </div>

                {partners.length > 0 && (
                  <div>
                    <span className="text-xs text-slate-500 block mb-1.5">Changes together with</span>
                    <div className="space-y-1.5">
                      {partners.map((p, i) => (
                        <div key={i} className="text-xs">
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-slate-300 font-mono truncate mr-2">{p.other.split('/').pop()}</span>
                            <span className="text-slate-500 font-mono shrink-0">
                              {p.co_count}× · {Math.round(p.score * 100)}%
                            </span>
                          </div>
                          <div className="h-1 rounded bg-white/5 overflow-hidden">
                            <div className="h-full rounded" style={{ width: `${Math.round(p.score * 100)}%`, background: scoreColor(p.score) }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {status === 'done' && !selected && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-aeon-surface/90 border border-aeon-border rounded-lg px-4 py-2 pointer-events-none">
              <p className="text-xs text-slate-400">Click a file to see its coupling partners · thicker edges = tighter coupling</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
