import { useState, useRef, useCallback, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { streamProvenance, getCommitDiff } from '../lib/api.js'
import {
  GitCommit, GitPullRequest, CircleDot, User, FileCode,
  Search, Loader2, AlertCircle, Info, X, ChevronRight,
  History, Layers, GitBranch, LayoutList, Sparkles,
  Plus, Minus, FileDiff,
} from 'lucide-react'

const NODE_ICONS = {
  File: FileCode, Commit: GitCommit, PullRequest: GitPullRequest,
  Issue: CircleDot, Developer: User,
}
const NODE_LABELS = {
  File: 'File', Commit: 'Commit', PullRequest: 'Pull Request',
  Issue: 'Issue', Developer: 'Developer',
}
const NODE_COLORS = {
  File: '#9cdef2', Commit: '#64748b', PullRequest: '#22c55e',
  Issue: '#f59e0b', Developer: '#a855f7',
}

const EXAMPLES = [
  { repo: 'expressjs/express', file: 'lib/application.js',     label: 'Express app' },
  { repo: 'psf/requests',      file: 'src/requests/models.py', label: 'requests models' },
]

// ── Timeline layout ────────────────────────────────────────────────────────
function computeTimelinePositions(nodes, links) {
  const commits = [...nodes.filter(n => n.type === 'Commit')]
    .sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0))

  const W = Math.max(500, commits.length * 90)
  const startX = -W / 2

  const pos = {}
  const fileNode = nodes.find(n => n.type === 'File')
  if (fileNode) pos[fileNode.id] = { fx: startX - 110, fy: 0 }

  const commitX = {}
  commits.forEach((c, i) => {
    const x = commits.length === 1 ? 0 : startX + i * (W / (commits.length - 1))
    pos[c.id] = { fx: x, fy: 0 }
    commitX[c.id] = x
  })

  // helper: resolve link endpoints to ids
  const id = (v) => (typeof v === 'object' ? v?.id : v) ?? ''

  // PRs: above commits — average x of connected commits
  const prX = {}
  links.forEach(l => {
    if (l.type === 'PART_OF' && commitX[id(l.source)] !== undefined)
      (prX[id(l.target)] = prX[id(l.target)] || []).push(commitX[id(l.source)])
  })
  nodes.filter(n => n.type === 'PullRequest').forEach(pr => {
    const xs = prX[pr.id] || [0]
    pos[pr.id] = { fx: xs.reduce((a, b) => a + b, 0) / xs.length, fy: -150 }
  })

  // Issues: above PRs
  const issueX = {}
  links.forEach(l => {
    if ((l.type === 'CLOSES' || l.type === 'REFERENCES') && pos[id(l.source)])
      (issueX[id(l.target)] = issueX[id(l.target)] || []).push(pos[id(l.source)].fx)
  })
  nodes.filter(n => n.type === 'Issue').forEach(issue => {
    const xs = issueX[issue.id] || [0]
    pos[issue.id] = { fx: xs.reduce((a, b) => a + b, 0) / xs.length, fy: -290 }
  })

  // Developers: below commits
  const devX = {}
  links.forEach(l => {
    if (l.type === 'AUTHORED_BY' && commitX[id(l.source)] !== undefined)
      (devX[id(l.target)] = devX[id(l.target)] || []).push(commitX[id(l.source)])
  })
  nodes.filter(n => n.type === 'Developer').forEach(dev => {
    const xs = devX[dev.id] || [0]
    pos[dev.id] = { fx: xs.reduce((a, b) => a + b, 0) / xs.length, fy: 150 }
  })

  return pos
}

// ── Diff renderer ─────────────────────────────────────────────────────────
function DiffView({ patch }) {
  if (!patch) return null
  return (
    <div className="font-mono text-xs overflow-x-auto">
      {patch.split('\n').map((line, i) => {
        const isAdd = line.startsWith('+') && !line.startsWith('+++')
        const isDel = line.startsWith('-') && !line.startsWith('---')
        const isHunk = line.startsWith('@@')
        return (
          <div
            key={i}
            className={[
              'px-2 py-px whitespace-pre leading-5',
              isAdd  ? 'bg-green-500/10 text-green-400' : '',
              isDel  ? 'bg-red-500/10 text-red-400'     : '',
              isHunk ? 'text-aeon-cyan/70 bg-aeon-cyan/5' : '',
              !isAdd && !isDel && !isHunk ? 'text-slate-500' : '',
            ].join(' ')}
          >
            {line || ' '}
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────
export default function Provenance() {
  const [repo, setRepo]           = useState('')
  const [filePath, setFilePath]   = useState('')
  const [maxCommits, setMaxCommits] = useState(12)
  const [status, setStatus]       = useState('idle')
  const [steps, setSteps]         = useState([])
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [meta, setMeta]           = useState(null)
  const [narrative, setNarrative] = useState('')
  const [selected, setSelected]   = useState(null)
  const [error, setError]         = useState('')
  const [layout, setLayout]       = useState('force')   // 'force' | 'timeline'
  const [diff, setDiff]           = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const esRef       = useRef(null)
  const graphRef    = useRef(null)
  // originalGraph holds the immutable server response — never passed directly to
  // ForceGraph2D so the library can't mutate it with x/y/vx/vy.
  const originalGraph = useRef({ nodes: [], links: [] })

  const abort = useCallback(() => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
  }, [])
  useEffect(() => () => abort(), [abort])

  // Build fresh (unmutated) copies from the original server data and apply positions.
  const applyLayout = useCallback((mode) => {
    const orig = originalGraph.current
    if (!orig.nodes.length) return

    // Deep-copy nodes (no x/y/vx/vy) and links (source/target stay as ID strings).
    const freshNodes = orig.nodes.map(n => ({ ...n }))
    const freshLinks = orig.links.map(l => ({ ...l }))

    if (mode === 'timeline') {
      const pos = computeTimelinePositions(freshNodes, freshLinks)
      setGraphData({
        nodes: freshNodes.map(n => {
          const p = pos[n.id] || {}
          // x/y must equal fx/fy so the very first frame renders at the right spot.
          return { ...n, ...p, ...(p.fx !== undefined ? { x: p.fx, y: p.fy } : {}) }
        }),
        links: freshLinks,
      })
    } else {
      setGraphData({ nodes: freshNodes, links: freshLinks })
    }
  }, [])

  function analyze() {
    if (!repo.trim() || !filePath.trim()) return
    abort()
    setStatus('loading')
    setSteps([])
    setGraphData({ nodes: [], links: [] })
    originalGraph.current = { nodes: [], links: [] }
    setMeta(null)
    setNarrative('')
    setSelected(null)
    setError('')
    setDiff(null)

    const es = streamProvenance(repo.trim(), filePath.trim(), maxCommits)
    esRef.current = es

    es.onmessage = (e) => {
      const event = JSON.parse(e.data)
      if (event.type === 'step') {
        setSteps(prev => [...prev, event.message])
      } else if (event.type === 'narrative') {
        setNarrative(event.text)
      } else if (event.type === 'result') {
        originalGraph.current = {
          nodes: event.nodes,
          links: event.edges,
        }
        applyLayout(layout)
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
      setError('Connection to backend lost. Is Aeon running?')
      setStatus('error')
      es.close()
    }
  }

  function switchLayout(mode) {
    setLayout(mode)
    applyLayout(mode)
  }

  const handleNodeClick = useCallback((node) => {
    setSelected(node)
    setDiff(null)
    if (node.type === 'Commit' && node.sha && meta?.repo) {
      setDiffLoading(true)
      getCommitDiff(meta.repo, node.sha)
        .then(d => setDiff(d))
        .catch(() => setDiff({ error: 'Could not load diff' }))
        .finally(() => setDiffLoading(false))
    }
  }, [meta])

  const paintNode = useCallback((node, ctx, globalScale) => {
    const size  = node.type === 'File' ? 10 : node.type === 'Developer' ? 7 : 8
    const color = node.color || '#64748b'
    const isSelected = selected?.id === node.id

    if (node.type === 'File') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, size + 5, 0, 2 * Math.PI)
      ctx.fillStyle = `${color}18`
      ctx.fill()
    }

    ctx.beginPath()
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
    ctx.fillStyle = isSelected ? '#ffffff' : color
    ctx.fill()
    ctx.strokeStyle = isSelected ? color : `${color}88`
    ctx.lineWidth   = isSelected ? 2.5 : 1.5
    ctx.stroke()

    if (globalScale >= 1.1 || node.type === 'File') {
      const label = node.label || node.id
      const fs = Math.max(10 / globalScale, 4.5)
      ctx.font      = `${node.type === 'File' ? 700 : 400} ${fs}px "Fira Code", monospace`
      ctx.fillStyle = isSelected ? color : '#cbd5e1'
      ctx.textAlign = 'center'
      ctx.fillText(label, node.x, node.y + size + fs + 1)
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
              <Layers size={16} className="text-aeon-cyan" />
              <h2 className="text-white font-semibold text-sm">Code Provenance</h2>
            </div>
            <p className="text-slate-500 text-xs leading-relaxed">
              Why is this code the way it is? Trace commits → PRs → issues with AI reasoning.
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
                placeholder="facebook/react"
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-aeon-cyan font-mono"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">File Path</label>
              <input
                value={filePath}
                onChange={e => setFilePath(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && analyze()}
                placeholder="src/index.js"
                className="w-full bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-aeon-cyan font-mono"
              />
            </div>

            {/* Commit depth */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Commits to trace</label>
              <div className="flex items-center gap-1.5">
                {[5, 10, 20, 30].map(n => (
                  <button key={n} onClick={() => setMaxCommits(n)}
                    className={['flex-1 py-1 rounded text-xs font-mono font-semibold border transition-colors',
                      maxCommits === n
                        ? 'bg-aeon-cyan/15 border-aeon-cyan text-aeon-cyan'
                        : 'bg-aeon-dark border-aeon-border text-slate-500 hover:text-slate-300',
                    ].join(' ')}>
                    {n}
                  </button>
                ))}
                <input type="number" min={5} max={30} value={maxCommits}
                  onChange={e => setMaxCommits(Math.min(30, Math.max(5, Number(e.target.value))))}
                  className="w-12 bg-aeon-dark border border-aeon-border rounded px-1 py-1 text-xs text-white text-center font-mono focus:outline-none focus:border-aeon-cyan"
                />
              </div>
              <p className="text-xs text-slate-600 mt-1">
                {maxCommits <= 10 ? '⚡ fast' : maxCommits <= 20 ? '⚖ balanced' : '🔍 thorough · needs token'}
              </p>
            </div>

            <button onClick={analyze}
              disabled={status === 'loading' || !repo.trim() || !filePath.trim()}
              className="w-full flex items-center justify-center gap-2 bg-aeon-cyan/10 hover:bg-aeon-cyan/20 border border-aeon-cyan/30 text-aeon-cyan rounded-lg px-4 py-2 text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
              {status === 'loading'
                ? <><Loader2 size={13} className="animate-spin" /> Tracing…</>
                : <><Search size={13} /> Trace Provenance</>}
            </button>
          </div>

          {/* Examples */}
          <div className="p-3 border-b border-aeon-border">
            <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Examples</p>
            {EXAMPLES.map(ex => (
              <button key={ex.label} onClick={() => { setRepo(ex.repo); setFilePath(ex.file) }}
                className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-xs hover:bg-white/5 transition-colors">
                <ChevronRight size={9} className="text-slate-600 shrink-0" />
                <span className="font-medium text-slate-300">{ex.label}</span>
                <span className="text-slate-600 truncate text-xs">{ex.file.split('/').pop()}</span>
              </button>
            ))}
          </div>

          {/* Progress */}
          {steps.length > 0 && (
            <div className="p-3 border-b border-aeon-border">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <History size={9} /> Progress
              </p>
              <div className="space-y-1">
                {steps.map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <div className="w-1 h-1 rounded-full bg-aeon-cyan mt-1.5 shrink-0" />
                    <span className="text-slate-400 leading-relaxed">{s}</span>
                  </div>
                ))}
                {status === 'loading' && (
                  <div className="flex items-center gap-1.5 text-xs text-slate-600 mt-1">
                    <Loader2 size={9} className="animate-spin" /><span>Working…</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Stats */}
          {meta && (
            <div className="p-3 border-b border-aeon-border">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider mb-2">Stats</p>
              <div className="grid grid-cols-2 gap-1.5">
                {[
                  { label: 'Commits', value: meta.commits,    color: NODE_COLORS.Commit },
                  { label: 'PRs',     value: meta.prs,        color: NODE_COLORS.PullRequest },
                  { label: 'Issues',  value: meta.issues,     color: NODE_COLORS.Issue },
                  { label: 'Authors', value: meta.developers, color: NODE_COLORS.Developer },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-aeon-dark rounded-lg p-2 text-center">
                    <div className="text-base font-bold font-mono" style={{ color }}>{value}</div>
                    <div className="text-xs text-slate-600">{label}</div>
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
              {Object.entries(NODE_LABELS).map(([type, label]) => {
                const Icon = NODE_ICONS[type]
                return (
                  <div key={type} className="flex items-center gap-2 text-xs text-slate-500">
                    <Icon size={11} style={{ color: NODE_COLORS[type] }} />
                    <span>{label}</span>
                  </div>
                )
              })}
            </div>
          </div>

        </div>
      </div>

      {/* ── Main area ───────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* ── AI Narrative banner ─────────────────────────────────── */}
        {narrative && (
          <div className="shrink-0 border-b border-aeon-border bg-aeon-surface px-5 py-3">
            <div className="flex items-start gap-3">
              <div className="shrink-0 mt-0.5 w-6 h-6 rounded-lg bg-aeon-cyan/10 border border-aeon-cyan/20 flex items-center justify-center">
                <Sparkles size={12} className="text-aeon-cyan" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-aeon-cyan uppercase tracking-wide mb-1">
                  AI Evolution Narrative · {meta?.file?.split('/').pop()}
                </p>
                <p className="text-sm text-slate-300 leading-relaxed">{narrative}</p>
              </div>
            </div>
          </div>
        )}

        {/* ── Graph toolbar ───────────────────────────────────────── */}
        {graphData.nodes.length > 0 && (
          <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-aeon-border bg-aeon-surface">
            <span className="text-xs text-slate-500 mr-1">Layout:</span>
            <button onClick={() => switchLayout('force')}
              className={['flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium border transition-colors',
                layout === 'force'
                  ? 'bg-aeon-cyan/10 border-aeon-cyan text-aeon-cyan'
                  : 'border-aeon-border text-slate-500 hover:text-slate-300',
              ].join(' ')}>
              <GitBranch size={11} /> Force
            </button>
            <button onClick={() => switchLayout('timeline')}
              className={['flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium border transition-colors',
                layout === 'timeline'
                  ? 'bg-aeon-cyan/10 border-aeon-cyan text-aeon-cyan'
                  : 'border-aeon-border text-slate-500 hover:text-slate-300',
              ].join(' ')}>
              <LayoutList size={11} /> Timeline
            </button>
            {layout === 'timeline' && (
              <span className="text-xs text-slate-600 ml-1">oldest → newest · scroll to zoom</span>
            )}
          </div>
        )}

        {/* ── Graph canvas ────────────────────────────────────────── */}
        <div className="flex-1 relative bg-aeon-dark overflow-hidden">
          {status === 'idle' && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Layers size={44} className="text-slate-700 mx-auto" />
                <p className="text-slate-500 text-sm">Enter a public GitHub repo and file path</p>
                <p className="text-slate-600 text-xs">Click an example on the left to start</p>
              </div>
            </div>
          )}

          {status === 'loading' && graphData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center space-y-2">
                <Loader2 size={30} className="text-aeon-cyan mx-auto animate-spin" />
                <p className="text-slate-400 text-sm">Building provenance graph…</p>
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
              onNodeClick={handleNodeClick}
              linkColor={l => l.type === 'CLOSES' ? '#22c55e55' : '#33415566'}
              linkWidth={l => l.type === 'CLOSES' ? 2 : 1.5}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              linkLabel={l => l.type}
              backgroundColor="#1e2430"
              cooldownTicks={layout === 'timeline' ? 0 : 80}
              nodeRelSize={6}
            />
          )}

          {/* ── Node detail panel ─────────────────────────────────── */}
          {selected && (
            <div className="absolute top-3 right-3 w-80 bg-aeon-surface border border-aeon-border rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[calc(100%-1.5rem)]">
              {/* Panel header */}
              <div className="px-4 py-3 flex items-center justify-between border-b border-aeon-border shrink-0"
                style={{ borderLeftColor: selected.color, borderLeftWidth: 3 }}>
                <div className="flex items-center gap-2">
                  {NODE_ICONS[selected.type] && (() => {
                    const Icon = NODE_ICONS[selected.type]
                    return <Icon size={13} style={{ color: selected.color }} />
                  })()}
                  <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
                    {NODE_LABELS[selected.type] || selected.type}
                  </span>
                </div>
                <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white transition-colors">
                  <X size={13} />
                </button>
              </div>

              <div className="overflow-y-auto flex-1">
                <div className="p-4 space-y-3">
                  {/* Title */}
                  <div>
                    <p className="text-white font-semibold text-sm">{selected.label}</p>
                    {selected.title && <p className="text-slate-400 text-xs mt-0.5">{selected.title}</p>}
                  </div>

                  {/* AI Why */}
                  {selected.why && (
                    <div className="bg-aeon-cyan/5 border border-aeon-cyan/20 rounded-lg p-3">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <Info size={10} className="text-aeon-cyan" />
                        <span className="text-xs font-semibold text-aeon-cyan uppercase tracking-wide">Why</span>
                      </div>
                      <p className="text-slate-300 text-xs leading-relaxed">{selected.why}</p>
                    </div>
                  )}

                  {/* Meta fields */}
                  <div className="space-y-1.5 text-xs">
                    {selected.sha && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">SHA</span>
                        <span className="text-slate-300 font-mono">{selected.sha.slice(0, 12)}</span>
                      </div>
                    )}
                    {selected.author && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">Author</span>
                        <span className="text-slate-300">{selected.author}</span>
                      </div>
                    )}
                    {selected.date && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">Date</span>
                        <span className="text-slate-300">{selected.date}</span>
                      </div>
                    )}
                    {selected.state && (
                      <div className="flex justify-between">
                        <span className="text-slate-500">State</span>
                        <span className={selected.state === 'open' ? 'text-green-400 font-medium' : 'text-slate-400'}>
                          {selected.state}
                        </span>
                      </div>
                    )}
                    {selected.message && (
                      <div>
                        <span className="text-slate-500 block mb-1">Message</span>
                        <p className="text-slate-300 font-mono text-xs leading-relaxed bg-aeon-dark rounded p-2 break-words">
                          {selected.message}
                        </p>
                      </div>
                    )}
                    {selected.full_path && (
                      <div>
                        <span className="text-slate-500 block mb-0.5">Path</span>
                        <p className="text-slate-300 font-mono text-xs break-all">{selected.full_path}</p>
                      </div>
                    )}
                  </div>

                  {/* GitHub link */}
                  {selected.url && (
                    <a href={selected.url} target="_blank" rel="noopener noreferrer"
                      className="block text-center py-1.5 rounded-lg border border-aeon-border text-slate-400 hover:text-white hover:border-aeon-cyan transition-colors text-xs">
                      View on GitHub ↗
                    </a>
                  )}

                  {/* ── Diff section (commits only) ──────────────── */}
                  {selected.type === 'Commit' && (
                    <div className="border-t border-aeon-border pt-3">
                      <div className="flex items-center gap-1.5 mb-2">
                        <FileDiff size={11} className="text-slate-400" />
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Diff</span>
                      </div>

                      {diffLoading && (
                        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
                          <Loader2 size={11} className="animate-spin" /> Loading diff…
                        </div>
                      )}

                      {diff?.error && (
                        <p className="text-xs text-red-400">{diff.error}</p>
                      )}

                      {diff && !diff.error && (
                        <div className="space-y-2">
                          {/* Stats summary */}
                          <div className="flex items-center gap-3 text-xs">
                            <span className="text-slate-500">{diff.files?.length} file{diff.files?.length !== 1 ? 's' : ''}</span>
                            <span className="text-green-400 flex items-center gap-0.5">
                              <Plus size={10} />{diff.stats?.additions ?? 0}
                            </span>
                            <span className="text-red-400 flex items-center gap-0.5">
                              <Minus size={10} />{diff.stats?.deletions ?? 0}
                            </span>
                          </div>

                          {/* Per-file diffs */}
                          {diff.files?.map((f, i) => (
                            <div key={i} className="rounded-lg overflow-hidden border border-aeon-border">
                              <div className="px-2 py-1 bg-aeon-dark flex items-center justify-between">
                                <span className="font-mono text-xs text-slate-300 truncate">{f.filename}</span>
                                <span className="text-xs text-slate-600 shrink-0 ml-2">
                                  <span className="text-green-400">+{f.additions}</span>
                                  {' '}
                                  <span className="text-red-400">-{f.deletions}</span>
                                </span>
                              </div>
                              {f.patch && <DiffView patch={f.patch} />}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Hint */}
          {status === 'done' && !selected && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-aeon-surface/90 border border-aeon-border rounded-lg px-4 py-2 pointer-events-none">
              <p className="text-xs text-slate-400">Click any node · commits show real diffs</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
