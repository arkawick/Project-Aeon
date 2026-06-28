import { useEffect, useRef, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import axios from 'axios'
import { Network, RefreshCw, X } from 'lucide-react'

const NODE_COLORS = {
  Incident: '#f97316',
  Pipeline: '#3b82f6',
  ErrorType: '#eab308',
  Fix: '#22c55e',
}

const LEGEND = Object.entries(NODE_COLORS).map(([label, color]) => ({ label, color }))

function truncate(str, n = 28) {
  return str.length > n ? str.slice(0, n) + '…' : str
}

export default function GraphView() {
  const containerRef = useRef(null)
  const graphRef = useRef(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  const fetchGraph = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await axios.get('http://localhost:8000/api/memory/graph')
      setGraphData({
        nodes: data.nodes.map(n => ({ ...n, name: n.id })),
        links: data.edges.map(e => ({ ...e, label: e.type })),
      })
    } catch (err) {
      setError('Could not load graph data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchGraph() }, [fetchGraph])

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      setDimensions({ width, height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const nodeColor = node => NODE_COLORS[node.label] ?? '#94a3b8'

  const drawNode = useCallback((node, ctx, globalScale) => {
    const r = node.label === 'Incident' ? 7 : 5
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = nodeColor(node)
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'
    ctx.lineWidth = 1 / globalScale
    ctx.stroke()

    if (globalScale >= 1.2) {
      const label = truncate(node.id, 20)
      ctx.font = `${10 / globalScale}px sans-serif`
      ctx.fillStyle = 'rgba(255,255,255,0.75)'
      ctx.textAlign = 'center'
      ctx.fillText(label, node.x, node.y + r + 8 / globalScale)
    }
  }, [])

  const handleNodeClick = useCallback(node => {
    setSelected(node)
    graphRef.current?.centerAt(node.x, node.y, 600)
    graphRef.current?.zoom(2.5, 600)
  }, [])

  const nodeLabel = node => `[${node.label}] ${node.id}`

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-purple-600 flex items-center justify-center">
            <Network size={16} className="text-white" />
          </div>
          <div>
            <h2 className="text-white font-semibold text-lg">Knowledge Graph</h2>
            <p className="text-slate-400 text-xs">
              {graphData.nodes.length} nodes · {graphData.links.length} edges
            </p>
          </div>
        </div>
        <button
          onClick={fetchGraph}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white text-sm transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 shrink-0">
        {LEGEND.map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: color }} />
            <span className="text-slate-400 text-xs">{label}</span>
          </div>
        ))}
      </div>

      {/* Graph canvas */}
      <div
        ref={containerRef}
        className="relative flex-1 rounded-xl border border-aeon-border bg-aeon-surface overflow-hidden"
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="flex items-center gap-2 text-slate-400 text-sm">
              <RefreshCw size={16} className="animate-spin" />
              Loading graph…
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            width={dimensions.width}
            height={dimensions.height}
            backgroundColor="transparent"
            nodeCanvasObject={drawNode}
            nodeLabel={nodeLabel}
            linkColor={() => 'rgba(148,163,184,0.25)'}
            linkWidth={1}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            linkLabel="label"
            onNodeClick={handleNodeClick}
            cooldownTicks={120}
            nodeRelSize={5}
          />
        )}

        {/* Selected node panel */}
        {selected && (
          <div className="absolute top-3 right-3 w-64 bg-aeon-dark border border-aeon-border rounded-xl p-4 z-20 shadow-xl">
            <div className="flex items-start justify-between gap-2 mb-3">
              <span
                className="px-2 py-0.5 rounded-full text-xs font-medium text-black"
                style={{ backgroundColor: NODE_COLORS[selected.label] ?? '#94a3b8' }}
              >
                {selected.label}
              </span>
              <button
                onClick={() => setSelected(null)}
                className="text-slate-500 hover:text-white transition-colors shrink-0"
              >
                <X size={14} />
              </button>
            </div>
            <p className="text-white text-sm font-medium break-words leading-snug">
              {selected.id}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
