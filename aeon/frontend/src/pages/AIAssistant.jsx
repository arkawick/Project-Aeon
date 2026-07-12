import { useState, useRef, useEffect } from 'react'
import { executeActions, approveAction, rejectAction, generatePostmortem, startOdysseusResearch } from '../lib/api.js'
import {
  Bot, Send, Loader2, AlertCircle, CheckCircle, Lightbulb,
  Brain, GitPullRequest, Zap, Clock, Search, ChevronRight, X,
  TrendingUp, Microscope, FileText, Copy, Download, Shield, ExternalLink,
} from 'lucide-react'

const ODYSSEUS_URL = 'http://localhost:7000'

const INITIAL_MESSAGE = {
  id: 0,
  role: 'assistant',
  text: "Hello! I'm Aeon, your AI ops assistant. Ask me about any build failure and I'll diagnose it using live tool calls and incident memory.",
  result: null,
  events: [],
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ConfidenceBar({ value }) {
  const color = value >= 85 ? 'bg-green-500' : value >= 70 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="mt-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-slate-500 text-xs flex items-center gap-1">
          <TrendingUp size={10} /> Confidence
        </span>
        <span className={`text-xs font-bold ${value >= 85 ? 'text-green-400' : value >= 70 ? 'text-yellow-400' : 'text-red-400'}`}>
          {value}%
        </span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}

function EventLog({ events }) {
  const filtered = events?.filter((e) => e.type !== 'text_delta')
  if (!filtered?.length) return null
  const icons = {
    node_start: <Brain size={12} className="text-indigo-400 shrink-0" />,
    tool_call: <Zap size={12} className="text-yellow-400 shrink-0" />,
    tool_result: <CheckCircle size={12} className="text-green-400 shrink-0" />,
    memory_results: <Search size={12} className="text-purple-400 shrink-0" />,
    memory_match_found: <Brain size={12} className="text-indigo-400 shrink-0" />,
    memory_written: <CheckCircle size={12} className="text-slate-400 shrink-0" />,
    claude_response: <Bot size={12} className="text-indigo-400 shrink-0" />,
  }
  return (
    <div className="mt-2 space-y-1 border-l-2 border-indigo-500/20 pl-3">
      {filtered.map((e, i) => (
        <div key={i} className="flex items-start gap-1.5 text-xs text-slate-500">
          {icons[e.type] || <ChevronRight size={12} className="text-slate-600 shrink-0" />}
          <span>{e.message || e.type}</span>
        </div>
      ))}
    </div>
  )
}

function MemoryMatchCard({ match }) {
  if (!match) return null
  const simPct = Math.round((match.similarity || 0) * 100)
  return (
    <div className="bg-indigo-950/50 border border-indigo-500/40 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-2">
        <Brain size={14} className="text-indigo-400" />
        <span className="text-indigo-400 text-xs font-semibold uppercase tracking-wide">Memory Match</span>
        <span className="ml-auto text-xs text-indigo-300 bg-indigo-500/20 px-2 py-0.5 rounded-full">{simPct}% similar</span>
      </div>
      <p className="text-slate-300 text-xs">
        <span className="text-indigo-300 font-mono">{match.id}</span>
        {match.time_ago && <span className="text-slate-500 ml-2">· {match.time_ago}</span>}
      </p>
      {match.match_reasons?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {match.match_reasons.map((r, i) => (
            <span key={i} className="text-[10px] text-indigo-300 bg-indigo-500/15 border border-indigo-500/25 px-1.5 py-0.5 rounded">{r}</span>
          ))}
        </div>
      )}
      {match.root_cause && <p className="text-slate-400 text-xs mt-1 line-clamp-2">{match.root_cause}</p>}
      {match.fix && <p className="text-green-400 text-xs mt-1 font-mono line-clamp-1">→ {match.fix}</p>}
    </div>
  )
}

function ActionPanel({ result, incidentId, onActionsExecuted }) {
  const [repo, setRepo] = useState('')
  const [executing, setExecuting] = useState(false)
  const [actionsResult, setActionsResult] = useState(null)
  const [approving, setApproving] = useState({})
  const [error, setError] = useState(null)

  async function handleExecute() {
    if (!repo.trim()) return
    setExecuting(true)
    setError(null)
    try {
      const res = await executeActions(result, incidentId, { repo: repo.trim() })
      setActionsResult(res)
      onActionsExecuted?.(res)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to execute actions.')
    } finally {
      setExecuting(false)
    }
  }

  async function handleApprove(actionId) {
    setApproving((p) => ({ ...p, [actionId]: 'approving' }))
    try {
      await approveAction(actionId)
      setApproving((p) => ({ ...p, [actionId]: 'approved' }))
    } catch {
      setApproving((p) => ({ ...p, [actionId]: 'error' }))
    }
  }

  async function handleReject(actionId) {
    setApproving((p) => ({ ...p, [actionId]: 'rejected' }))
    await rejectAction(actionId)
  }

  if (actionsResult) {
    return (
      <div className="mt-3 space-y-2">
        {actionsResult.executed?.map((a, i) => (
          <div key={i} className="flex items-center gap-2 text-xs text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
            <CheckCircle size={12} />
            <span>{a.description}</span>
            {a.url && <a href={a.url} target="_blank" rel="noreferrer" className="ml-auto text-green-300 underline">View →</a>}
          </div>
        ))}
        {actionsResult.pending?.map((a) => (
          <div key={a.id} className="bg-yellow-950/40 border border-yellow-500/30 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <GitPullRequest size={12} className="text-yellow-400" />
              <span className="text-yellow-400 text-xs font-semibold">PR Proposal — Awaiting Approval</span>
              <span className="ml-auto text-xs text-yellow-300 bg-yellow-500/20 px-2 py-0.5 rounded-full">{a.confidence}% confidence</span>
            </div>
            <p className="text-slate-300 text-xs mb-2">{a.description}</p>
            <div className="flex gap-2">
              <button onClick={() => handleApprove(a.id)} disabled={!!approving[a.id]}
                className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white rounded-md text-xs transition-colors">
                <CheckCircle size={11} />
                {approving[a.id] === 'approving' ? 'Creating PR...' : approving[a.id] === 'approved' ? 'PR Created ✓' : approving[a.id] === 'error' ? 'Error — retry?' : 'Approve & Create PR'}
              </button>
              <button onClick={() => handleReject(a.id)} disabled={!!approving[a.id]}
                className="flex items-center gap-1 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-300 rounded-md text-xs transition-colors">
                <X size={11} /> Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="mt-3 pt-3 border-t border-aeon-border">
      <p className="text-slate-500 text-xs mb-2">Execute actions (enter GitHub repo name):</p>
      {error && <p className="text-red-400 text-xs mb-2 flex items-center gap-1"><AlertCircle size={11} /> {error}</p>}
      <div className="flex gap-2">
        <input value={repo} onChange={(e) => setRepo(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
          placeholder="repo-name"
          className="flex-1 bg-aeon-dark border border-aeon-border rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500" />
        <button onClick={handleExecute} disabled={executing || !repo.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs transition-colors">
          {executing ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
          Execute
        </button>
      </div>
    </div>
  )
}

// Post-mortem modal
function PostmortemModal({ markdown, onClose }) {
  function handleCopy() {
    navigator.clipboard.writeText(markdown)
  }
  function handleDownload() {
    const blob = new Blob([markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'post-mortem.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-aeon-surface border border-aeon-border rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-aeon-border shrink-0">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-indigo-400" />
            <h2 className="text-white font-semibold">Incident Post-mortem</h2>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={handleCopy} className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-xs transition-colors">
              <Copy size={12} /> Copy
            </button>
            <button onClick={handleDownload} className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs transition-colors">
              <Download size={12} /> Download .md
            </button>
            <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-white/5 transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <pre className="text-slate-300 text-xs font-mono whitespace-pre-wrap leading-relaxed">{markdown}</pre>
        </div>
      </div>
    </div>
  )
}

async function openInOdysseus(query) {
  try {
    const res = await startOdysseusResearch(query)
    window.open(res.odysseus_url || ODYSSEUS_URL, '_blank', 'noopener,noreferrer')
  } catch {
    window.open(ODYSSEUS_URL, '_blank', 'noopener,noreferrer')
  }
}

// Quick analysis result card
function AnalysisCard({ result, incidentId, query, onPostmortem }) {
  const primaryMatch = result.memory_match || result.memory_matches?.[0]
  const extraMatches = result.memory_matches?.slice(1) || []

  return (
    <div className="mt-3 space-y-3">
      <div className="bg-red-950/40 border border-red-500/30 rounded-lg p-3">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle size={14} className="text-red-400" />
          <span className="text-red-400 text-xs font-semibold uppercase tracking-wide">Root Cause</span>
        </div>
        <p className="text-slate-200 text-sm leading-relaxed">{result.root_cause}</p>
        <ConfidenceBar value={result.confidence} />
      </div>

      {primaryMatch && <MemoryMatchCard match={primaryMatch} />}
      {extraMatches.length > 0 && (
        <div>
          <p className="text-slate-500 text-xs font-semibold uppercase tracking-wide mb-2">Also Similar</p>
          <div className="space-y-2">{extraMatches.map((m) => <MemoryMatchCard key={m.id} match={m} />)}</div>
        </div>
      )}

      {result.suggested_fix && (
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Lightbulb size={14} className="text-yellow-400" />
            <span className="text-yellow-400 text-xs font-semibold uppercase tracking-wide">Suggested Fix</span>
          </div>
          <pre className="text-green-300 text-xs font-mono whitespace-pre-wrap">{result.suggested_fix}</pre>
        </div>
      )}

      {result.similar_incidents?.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {result.similar_incidents.map((id) => (
            <span key={id} className="px-2 py-0.5 bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 rounded-full text-xs">{id}</span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1 flex-wrap">
        <button onClick={() => onPostmortem(result, query)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-xs transition-colors">
          <FileText size={12} /> Generate Post-mortem
        </button>
        <button onClick={() => openInOdysseus(query)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/60 hover:bg-purple-800/60 border border-purple-500/30 text-purple-300 rounded-lg text-xs transition-colors">
          <ExternalLink size={12} /> Research deeper in Odysseus
        </button>
      </div>

      <ActionPanel result={result} incidentId={incidentId} />
    </div>
  )
}

// Deep research result card
function ResearchReportCard({ result, query, onPostmortem }) {
  return (
    <div className="mt-3 space-y-3">
      {result.title && (
        <div className="flex items-center gap-2">
          <Microscope size={16} className="text-indigo-400 shrink-0" />
          <h3 className="text-white font-semibold text-sm">{result.title}</h3>
        </div>
      )}

      {result.executive_summary && (
        <div className="bg-indigo-950/40 border border-indigo-500/30 rounded-lg p-3">
          <p className="text-indigo-300 text-xs font-semibold uppercase tracking-wide mb-1">Executive Summary</p>
          <p className="text-slate-200 text-sm leading-relaxed">{result.executive_summary}</p>
          <ConfidenceBar value={result.confidence} />
        </div>
      )}

      <div className="bg-red-950/40 border border-red-500/30 rounded-lg p-3">
        <p className="text-red-400 text-xs font-semibold uppercase tracking-wide mb-1">Root Cause</p>
        <p className="text-slate-200 text-sm leading-relaxed">{result.root_cause}</p>
      </div>

      {result.contributing_factors?.length > 0 && (
        <div className="bg-aeon-surface border border-aeon-border rounded-lg p-3">
          <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-2">Contributing Factors</p>
          <ul className="space-y-1">
            {result.contributing_factors.map((f, i) => (
              <li key={i} className="text-slate-300 text-xs flex items-start gap-2">
                <span className="text-orange-400 mt-0.5">•</span>{f}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.impact && (
        <div className="bg-orange-950/30 border border-orange-500/20 rounded-lg p-3">
          <p className="text-orange-400 text-xs font-semibold uppercase tracking-wide mb-1">Impact</p>
          <p className="text-slate-300 text-xs">{result.impact}</p>
        </div>
      )}

      {result.resolution && (
        <div className="bg-slate-900 border border-slate-700 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Lightbulb size={14} className="text-yellow-400" />
            <span className="text-yellow-400 text-xs font-semibold uppercase tracking-wide">Resolution</span>
          </div>
          <pre className="text-green-300 text-xs font-mono whitespace-pre-wrap">{result.resolution}</pre>
        </div>
      )}

      {result.action_items?.length > 0 && (
        <div className="bg-aeon-surface border border-aeon-border rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Shield size={14} className="text-blue-400" />
            <span className="text-blue-400 text-xs font-semibold uppercase tracking-wide">Action Items</span>
          </div>
          <ul className="space-y-1">
            {result.action_items.map((a, i) => (
              <li key={i} className="text-slate-300 text-xs flex items-start gap-2">
                <span className="text-blue-400 mt-0.5">☐</span>{a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(result.memory_match || result.memory_matches?.[0]) && (
        <MemoryMatchCard match={result.memory_match || result.memory_matches[0]} />
      )}

      <div className="flex items-center gap-2 pt-1 flex-wrap">
        <button onClick={() => onPostmortem(result, query)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs transition-colors">
          <FileText size={12} /> Generate Post-mortem
        </button>
        <a href={ODYSSEUS_URL} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-900/60 hover:bg-purple-800/60 border border-purple-500/30 text-purple-300 rounded-lg text-xs transition-colors">
          <ExternalLink size={12} /> Continue in Odysseus Chat
        </a>
      </div>
    </div>
  )
}

function ThinkingBubble({ events, streamingText, mode }) {
  const nonDeltaEvents = events.filter((e) => e.type !== 'text_delta')
  return (
    <div className="flex gap-3 justify-start">
      <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center shrink-0 mt-0.5">
        {mode === 'research' ? <Microscope size={16} className="text-white" /> : <Bot size={16} className="text-white" />}
      </div>
      <div className="bg-aeon-surface border border-aeon-border rounded-2xl rounded-tl-sm px-4 py-3 max-w-2xl">
        <div className="flex items-center gap-2 mb-2">
          <Loader2 size={14} className="text-indigo-400 animate-spin" />
          <span className="text-slate-400 text-sm">{mode === 'research' ? 'Aeon is researching...' : 'Aeon is thinking...'}</span>
        </div>
        <EventLog events={nonDeltaEvents} />
        {streamingText && (
          <div className="mt-2 text-slate-300 text-sm leading-relaxed font-mono text-xs bg-slate-900/60 rounded-lg p-2 border border-slate-700/50">
            {streamingText}
            <span className="inline-block w-1.5 h-3.5 bg-indigo-400 ml-0.5 animate-pulse align-middle" />
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AIAssistant() {
  const [messages, setMessages] = useState([INITIAL_MESSAGE])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('quick')
  const [streaming, setStreaming] = useState(false)
  const [liveEvents, setLiveEvents] = useState([])
  const [streamingText, setStreamingText] = useState('')
  const [connectionError, setConnectionError] = useState(false)
  const [postmortemMarkdown, setPostmortemMarkdown] = useState(null)
  const [generatingPostmortem, setGeneratingPostmortem] = useState(false)
  const bottomRef = useRef(null)
  const esRef = useRef(null)
  const streamingTextRef = useRef('')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, liveEvents, streamingText])

  async function handleGeneratePostmortem(result, query) {
    setGeneratingPostmortem(true)
    try {
      const md = await generatePostmortem(result, query)
      setPostmortemMarkdown(md)
    } catch {
      setPostmortemMarkdown('# Error\n\nFailed to generate post-mortem. Please try again.')
    } finally {
      setGeneratingPostmortem(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    const query = input.trim()
    if (!query || streaming) return

    const userMsg = { id: Date.now(), role: 'user', text: query, result: null, events: [], mode }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLiveEvents([])
    setStreamingText('')
    setStreaming(true)
    setConnectionError(false)
    streamingTextRef.current = ''

    const collectedEvents = []
    let finalResult = null

    const url = mode === 'research'
      ? `/api/ai/research/stream?query=${encodeURIComponent(query)}`
      : `/api/ai/stream?query=${encodeURIComponent(query)}`

    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      if (e.data === '[DONE]') {
        es.close()
        setStreaming(false)
        setLiveEvents([])
        setStreamingText('')
        streamingTextRef.current = ''
        const assistantMsg = {
          id: Date.now() + 1,
          role: 'assistant',
          text: finalResult ? 'Analysis complete.' : 'No result returned.',
          result: finalResult,
          events: collectedEvents,
          incidentId: finalResult?.incident_id,
          mode,
          query,
        }
        setMessages((prev) => [...prev, assistantMsg])
        return
      }
      try {
        const event = JSON.parse(e.data)
        if (event.type === 'result') {
          finalResult = event.content
        } else if (event.type === 'text_delta') {
          streamingTextRef.current += event.text
          setStreamingText(streamingTextRef.current)
          collectedEvents.push(event)
        } else {
          collectedEvents.push(event)
          setLiveEvents([...collectedEvents])
        }
      } catch { /* ignore parse errors */ }
    }

    es.onerror = () => {
      es.close()
      setStreaming(false)
      setLiveEvents([])
      setStreamingText('')
      streamingTextRef.current = ''
      if (!finalResult) {
        setConnectionError(true)
        setMessages((prev) => [...prev, {
          id: Date.now() + 1,
          role: 'assistant',
          text: 'Connection error. Is the backend running on port 8000?',
          result: null,
          events: [],
          isError: true,
        }])
      }
    }
  }

  return (
    <div className="flex flex-col h-full" style={{ maxHeight: 'calc(100vh - 3rem)' }}>
      {/* Header + mode toggle */}
      <div className="mb-4 shrink-0 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AI Assistant</h1>
          <p className="text-slate-400 text-sm mt-1">Powered by Aeon AI · LangGraph · ChromaDB memory</p>
        </div>
        <div className="flex bg-aeon-surface border border-aeon-border rounded-lg p-1 gap-1">
          <button
            onClick={() => setMode('quick')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${mode === 'quick' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            <Zap size={12} /> Quick Analysis
          </button>
          <button
            onClick={() => setMode('research')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${mode === 'research' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            <Microscope size={12} /> Deep Research
          </button>
        </div>
      </div>

      {mode === 'research' && (
        <div className="mb-3 shrink-0 bg-indigo-950/40 border border-indigo-500/20 rounded-lg px-3 py-2 flex items-center gap-2">
          <Microscope size={13} className="text-indigo-400 shrink-0" />
          <p className="text-indigo-300 text-xs">Deep Research mode — more tool calls, exhaustive investigation, richer report with contributing factors, impact, and action items.</p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-1 min-h-0">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${msg.isError ? 'bg-red-600' : 'bg-indigo-600'}`}>
                {msg.mode === 'research' ? <Microscope size={16} className="text-white" /> : <Bot size={16} className="text-white" />}
              </div>
            )}
            <div className={`max-w-2xl ${msg.role === 'user' ? 'bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5' : ''}`}>
              {msg.role === 'assistant' ? (
                <div className={`bg-aeon-surface border rounded-2xl rounded-tl-sm px-4 py-3 ${msg.isError ? 'border-red-500/40' : 'border-aeon-border'}`}>
                  {msg.events?.filter((e) => e.type !== 'text_delta').length > 0 && <EventLog events={msg.events} />}
                  <p className={`text-sm mt-2 ${msg.isError ? 'text-red-400' : 'text-slate-200'}`}>{msg.text}</p>
                  {msg.result && (
                    msg.mode === 'research'
                      ? <ResearchReportCard result={msg.result} query={msg.query} onPostmortem={handleGeneratePostmortem} />
                      : <AnalysisCard result={msg.result} incidentId={msg.incidentId} query={msg.query} onPostmortem={handleGeneratePostmortem} />
                  )}
                </div>
              ) : (
                <p className="text-sm">{msg.text}</p>
              )}
            </div>
          </div>
        ))}

        {streaming && <ThinkingBubble events={liveEvents} streamingText={streamingText} mode={mode} />}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-3 shrink-0">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={mode === 'research'
            ? 'What incident should I investigate deeply? e.g. "Investigate the Android build failures this week"'
            : 'Ask about a build failure, e.g. "Why did deploy-staging fail?"'}
          disabled={streaming}
          className="flex-1 bg-aeon-surface border border-aeon-border rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="px-4 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl transition-colors flex items-center gap-2"
        >
          {streaming
            ? <Loader2 size={16} className="animate-spin" />
            : mode === 'research' ? <Microscope size={16} /> : <Send size={16} />}
          <span className="text-sm font-medium">
            {streaming ? (mode === 'research' ? 'Researching...' : 'Analyzing...') : mode === 'research' ? 'Research' : 'Analyze'}
          </span>
        </button>
      </form>

      {generatingPostmortem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-aeon-surface border border-aeon-border rounded-xl px-6 py-4 flex items-center gap-3">
            <Loader2 size={20} className="text-indigo-400 animate-spin" />
            <span className="text-white text-sm">Generating post-mortem...</span>
          </div>
        </div>
      )}

      {postmortemMarkdown && (
        <PostmortemModal markdown={postmortemMarkdown} onClose={() => setPostmortemMarkdown(null)} />
      )}
    </div>
  )
}
