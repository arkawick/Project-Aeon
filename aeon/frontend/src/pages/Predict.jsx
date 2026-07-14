import { useState, useRef, useCallback, useEffect } from 'react'
import { streamPredict, getPredictStats, postPredictToPr } from '../lib/api.js'
import {
  Gauge, Loader2, AlertCircle, ShieldAlert, AlertTriangle, CheckCircle,
  Brain, GitBranch, Package, ChevronRight, ListChecks, X, FileWarning, Activity,
  TrendingUp, Send, Target,
} from 'lucide-react'

const CONF_STYLE = {
  high:   'bg-green-500/15 text-green-400 border-green-500/30',
  medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  low:    'bg-slate-500/15 text-slate-400 border-slate-500/30',
}
const CI_STYLE = {
  failed:  'text-red-400',
  passed:  'text-green-400',
  pending: 'text-amber-400',
  none:    'text-slate-500',
}

const EXAMPLE_REPOS = ['expressjs/express', 'pallets/flask', 'psf/requests']

const VERDICT_STYLE = {
  BLOCK:   { color: '#ef4444', ring: 'text-red-500',    chip: 'bg-red-500/15 text-red-400 border-red-500/30',       icon: ShieldAlert,   label: 'Likely to FAIL' },
  CAUTION: { color: '#f59e0b', ring: 'text-amber-500',  chip: 'bg-amber-500/15 text-amber-400 border-amber-500/30', icon: AlertTriangle, label: 'Merge with CAUTION' },
  PASS:    { color: '#22c55e', ring: 'text-green-500',  chip: 'bg-green-500/15 text-green-400 border-green-500/30', icon: CheckCircle,   label: 'Looks SAFE' },
}

// Circular probability gauge
function Gauge_({ prob, verdict }) {
  const style = VERDICT_STYLE[verdict] || VERDICT_STYLE.CAUTION
  const r = 54, c = 2 * Math.PI * r
  const off = c * (1 - prob / 100)
  return (
    <div className="relative w-40 h-40 shrink-0">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={r} fill="none" stroke="currentColor" strokeWidth="10" className="text-slate-800" />
        <circle cx="64" cy="64" r={r} fill="none" stroke={style.color} strokeWidth="10" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={off} style={{ transition: 'stroke-dashoffset 1s ease' }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-white">{prob}%</span>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">fail risk</span>
      </div>
    </div>
  )
}

function SignalBar({ label, value, icon: Icon, weight }) {
  const pct = Math.round(value * 100)
  return (
    <div>
      <div className="flex items-center justify-between mb-1 text-xs">
        <span className="text-slate-400 flex items-center gap-1.5"><Icon size={12} /> {label}</span>
        <span className="text-slate-500">{pct}% <span className="text-slate-600">· w{weight}</span></span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className="h-full rounded-full bg-indigo-500 transition-all duration-700" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// Learning-loop scoreboard: how accurate the gate has been vs real build outcomes
function LearningCard({ stats }) {
  if (!stats || !stats.resolved) return null
  const acc = Math.round((stats.accuracy || 0) * 100)
  return (
    <div className="bg-aeon-surface border border-aeon-border rounded-xl p-4 mb-5">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp size={14} className="text-green-400" />
        <span className="text-slate-300 text-xs font-semibold uppercase tracking-wide">Gate learning</span>
        <span className="text-[10px] text-slate-500">· scored vs real build outcomes</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div><div className="text-2xl font-bold text-white">{acc}%</div><div className="text-[10px] text-slate-500 uppercase">accuracy</div></div>
        <div><div className="text-2xl font-bold text-white">{stats.resolved}</div><div className="text-[10px] text-slate-500 uppercase">builds scored</div></div>
        <div><div className="text-2xl font-bold text-white">{stats.brier ?? '—'}</div><div className="text-[10px] text-slate-500 uppercase">brier ↓</div></div>
        <div><div className="text-2xl font-bold text-white">{stats.calibration_factor ?? '—'}×</div><div className="text-[10px] text-slate-500 uppercase">calibration</div></div>
      </div>
      {stats.recent?.length > 0 && (
        <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-aeon-border flex-wrap">
          <span className="text-[10px] text-slate-500 mr-1">recent:</span>
          {stats.recent.map((r, i) => (
            <span key={i} title={`${r.repo} #${r.pr}: predicted ${r.verdict} ${r.probability}%, actual ${r.actual}`}
                  className={`w-2.5 h-2.5 rounded-full ${r.correct ? 'bg-green-500' : 'bg-red-500'}`} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Predict() {
  const [repo, setRepo]   = useState('')
  const [pr, setPr]       = useState('')
  const [status, setStatus] = useState('idle')  // idle | streaming | done | error
  const [steps, setSteps] = useState([])
  const [signals, setSignals] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [stats, setStats] = useState(null)
  const [posting, setPosting] = useState(false)
  const [postMsg, setPostMsg] = useState('')
  const esRef = useRef(null)

  const loadStats = useCallback(() => { getPredictStats().then(setStats).catch(() => {}) }, [])
  useEffect(() => { loadStats() }, [loadStats])

  async function postToPr() {
    if (!result || !repo || !pr) return
    if (!window.confirm(`Post the Merge Gate verdict as a comment + status check on ${repo} #${pr}?\n\nThis writes to GitHub and needs a write-scoped token + your access to that repo.`)) return
    setPosting(true); setPostMsg('')
    try {
      const res = await postPredictToPr(repo.trim(), parseInt(pr))
      const ok = res?.comment?.posted
      setPostMsg(ok ? `Posted to ${repo} #${pr}` : (res?.comment?.error || res?.error || 'Post failed — check token write access.'))
    } catch (e) {
      setPostMsg('Post failed — check backend / token.')
    } finally { setPosting(false) }
  }

  const abort = useCallback(() => {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
  }, [])
  useEffect(() => () => abort(), [abort])

  function run() {
    const prNum = parseInt(pr)
    if (!repo.trim() || !prNum) return
    abort()
    setStatus('streaming'); setSteps([]); setSignals(null); setResult(null); setError('')

    const es = streamPredict(repo.trim(), prNum)
    esRef.current = es
    es.onmessage = (e) => {
      let ev
      try { ev = JSON.parse(e.data) } catch { return }
      if (ev.type === 'step') setSteps(s => [...s, ev.message])
      else if (ev.type === 'signals') setSignals(ev)
      else if (ev.type === 'result') { setResult(ev); setStatus('done'); abort(); loadStats() }
      else if (ev.type === 'error') { setError(ev.message); setStatus('error'); abort() }
    }
    es.onerror = () => {
      abort()
      if (!result) { setError('Connection lost. Is the backend running on :8000?'); setStatus('error') }
    }
  }

  const style = result ? (VERDICT_STYLE[result.verdict] || VERDICT_STYLE.CAUTION) : null

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Gauge size={22} className="text-indigo-400" /> Predictive Merge Gate
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Will this PR's build fail — <span className="text-slate-300">before</span> you run it? Forecast from incident memory,
          co-change hanging points, and risk surface.
        </p>
      </div>

      {/* Input */}
      <div className="bg-aeon-surface border border-aeon-border rounded-xl p-4 mb-5">
        <div className="flex gap-2 flex-wrap">
          <input value={repo} onChange={e => setRepo(e.target.value)} placeholder="owner/repo"
                 onKeyDown={e => e.key === 'Enter' && run()}
                 className="flex-1 min-w-[200px] bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500" />
          <input value={pr} onChange={e => setPr(e.target.value.replace(/\D/g, ''))} placeholder="PR #"
                 onKeyDown={e => e.key === 'Enter' && run()}
                 className="w-28 bg-aeon-dark border border-aeon-border rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500" />
          <button onClick={run} disabled={status === 'streaming' || !repo.trim() || !pr}
                  className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm transition-colors">
            {status === 'streaming' ? <Loader2 size={15} className="animate-spin" /> : <Gauge size={15} />} Forecast
          </button>
        </div>
        <div className="flex gap-2 mt-2 flex-wrap items-center">
          <span className="text-xs text-slate-600">Try:</span>
          {EXAMPLE_REPOS.map(r => (
            <button key={r} onClick={() => setRepo(r)} className="text-xs text-indigo-400 hover:text-indigo-300 hover:underline">{r}</button>
          ))}
          <span className="text-xs text-slate-600">· e.g. express PR 7233</span>
        </div>
      </div>

      {/* Learning scoreboard */}
      <LearningCard stats={stats} />

      {/* Live steps */}
      {status === 'streaming' && (
        <div className="bg-aeon-surface border border-aeon-border rounded-xl p-4 mb-5 space-y-1.5">
          {steps.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-slate-400">
              <ChevronRight size={12} className="text-indigo-400 shrink-0 mt-0.5" /> {s}
            </div>
          ))}
          <div className="flex items-center gap-2 text-xs text-indigo-400 pt-1">
            <Loader2 size={12} className="animate-spin" /> forecasting…
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-950/40 border border-red-500/30 rounded-xl p-4 mb-5 flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Result */}
      {result && style && (
        <div className="space-y-4">
          {/* Verdict + gauge */}
          <div className="bg-aeon-surface border rounded-xl p-5 flex items-center gap-6" style={{ borderColor: style.color + '55' }}>
            <Gauge_ prob={result.probability} verdict={result.verdict} />
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${style.chip}`}>
                  <style.icon size={13} /> {style.label}
                </div>
                {result.confidence && (
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold uppercase tracking-wide ${CONF_STYLE[result.confidence] || CONF_STYLE.low}`}>
                    {result.confidence} confidence
                  </span>
                )}
              </div>
              <p className="text-slate-200 text-sm leading-relaxed mt-2">{result.narrative}</p>
              {result.ci?.detail && (
                <p className={`text-xs mt-1.5 flex items-center gap-1.5 ${CI_STYLE[result.ci.state] || CI_STYLE.none}`}>
                  <Activity size={12} /> CI: {result.ci.detail}
                </p>
              )}
              {result.meta?.pr_url && (
                <a href={result.meta.pr_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-400 hover:underline mt-1 inline-block">
                  {result.meta.repo} #{result.meta.pr} · {result.meta.pr_title}
                </a>
              )}
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <button onClick={postToPr} disabled={posting}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs transition-colors">
                  {posting ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Post verdict to PR
                </button>
                {postMsg && <span className="text-xs text-slate-400">{postMsg}</span>}
              </div>
            </div>
          </div>

          {/* Signal breakdown */}
          {signals && (
            <div className="bg-aeon-surface border border-aeon-border rounded-xl p-4">
              <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-3">Why — signal breakdown</p>
              <div className="space-y-3">
                <SignalBar label="Resembles a past failure" value={signals.memory} icon={Brain} weight={result.meta.weights.memory} />
                <SignalBar label="Hanging points (coupled files left unchanged)" value={signals.hanging} icon={GitBranch} weight={result.meta.weights.hanging} />
                <SignalBar label="PR shape (tests, size, deps)" value={signals.shape} icon={FileWarning} weight={result.meta.weights.shape} />
                <SignalBar label="High-risk file classes touched" value={signals.risk} icon={Package} weight={result.meta.weights.risk} />
              </div>
              {result.shape_reasons?.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-3 pt-3 border-t border-aeon-border">
                  {result.shape_reasons.map((r, i) => (
                    <span key={i} className="text-[10px] text-amber-300 bg-amber-500/10 border border-amber-500/25 px-1.5 py-0.5 rounded">{r}</span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Hanging points */}
          {result.hanging_points?.length > 0 && (
            <div className="bg-amber-950/30 border border-amber-500/25 rounded-xl p-4">
              <p className="text-amber-400 text-xs font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <GitBranch size={13} /> Hanging points
              </p>
              <div className="space-y-2">
                {result.hanging_points.map((h, i) => (
                  <div key={i} className="text-xs text-slate-300">
                    Changed <span className="font-mono text-amber-300">{h.changed.split('/').pop()}</span> but not its
                    coupled <span className="font-mono text-amber-300">{h.missing.split('/').pop()}</span>
                    <span className="text-slate-500"> — change together {h.co_count}× ({Math.round(h.score * 100)}% coupling)</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Memory matches */}
          {result.memory_matches?.length > 0 && (
            <div className="bg-indigo-950/40 border border-indigo-500/30 rounded-xl p-4">
              <p className="text-indigo-400 text-xs font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <Brain size={13} /> Past incidents this resembles
              </p>
              <div className="space-y-2">
                {result.memory_matches.map((m, i) => (
                  <div key={i} className="text-xs">
                    <span className="font-mono text-indigo-300">{m.incident_id}</span>
                    <span className="text-slate-500 ml-2">{Math.round(m.similarity * 100)}% similar</span>
                    {m.matched_files?.length > 0 && <span className="text-slate-500"> · shares {m.matched_files.join(', ')}</span>}
                    {m.root_cause && <p className="text-slate-400 mt-0.5 line-clamp-2">{m.root_cause}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Must test */}
          {result.must_test?.length > 0 && (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
              <p className="text-slate-300 text-xs font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5">
                <ListChecks size={13} className="text-green-400" /> Run these before merge
              </p>
              <ul className="space-y-1.5">
                {result.must_test.map((t, i) => (
                  <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                    <span className="text-green-400 mt-0.5">☐</span>{t}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
