import { useEffect, useState } from 'react'
import { getWorkflows, triggerWorkflow } from '../lib/api.js'
import { Workflow, Play, CheckCircle, XCircle, Loader2, Clock } from 'lucide-react'

function WorkflowCard({ workflow }) {
  const [status, setStatus] = useState('idle') // idle | loading | success | error
  const [message, setMessage] = useState('')

  async function handleTrigger() {
    setStatus('loading')
    try {
      const result = await triggerWorkflow(workflow.id, {})
      if (result.triggered) {
        setStatus('success')
        setMessage(`Triggered (execution: ${result.execution_id || '—'})`)
      } else {
        setStatus('error')
        setMessage(result.error || 'Trigger failed')
      }
    } catch (err) {
      setStatus('error')
      setMessage(err.message || 'Network error')
    } finally {
      setTimeout(() => { setStatus('idle'); setMessage('') }, 3000)
    }
  }

  return (
    <div className="bg-aeon-surface border border-aeon-border rounded-xl p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-indigo-500/20 shrink-0">
            <Workflow size={18} className="text-indigo-400" />
          </div>
          <div className="min-w-0">
            <p className="text-white font-medium text-sm">{workflow.name}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className={`text-xs px-2 py-0.5 rounded-full ${workflow.active ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-slate-400'}`}>
                {workflow.active ? 'Active' : 'Inactive'}
              </span>
              <span className="text-xs text-slate-500">trigger: {workflow.trigger || 'webhook'}</span>
            </div>
            {workflow.last_run && (
              <div className="flex items-center gap-1 mt-1">
                <Clock size={10} className="text-slate-500" />
                <span className="text-xs text-slate-500">Last run: {new Date(workflow.last_run).toLocaleString()}</span>
              </div>
            )}
          </div>
        </div>

        <button
          onClick={handleTrigger}
          disabled={status === 'loading'}
          className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            status === 'success' ? 'bg-green-600 text-white' :
            status === 'error' ? 'bg-red-600/50 text-red-300' :
            'bg-indigo-600 hover:bg-indigo-500 text-white'
          } disabled:opacity-50`}
        >
          {status === 'loading' ? <Loader2 size={14} className="animate-spin" /> :
           status === 'success' ? <CheckCircle size={14} /> :
           status === 'error' ? <XCircle size={14} /> :
           <Play size={14} />}
          {status === 'loading' ? 'Triggering...' :
           status === 'success' ? 'Triggered!' :
           status === 'error' ? 'Failed' :
           'Trigger'}
        </button>
      </div>

      {message && (
        <div className={`mt-3 text-xs px-3 py-2 rounded-lg ${status === 'success' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
          {message}
        </div>
      )}
    </div>
  )
}

export default function Workflows() {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getWorkflows().then(setWorkflows).catch(() => setWorkflows([])).finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">n8n Workflows</h1>
        <p className="text-slate-400 text-sm mt-1">Trigger automation workflows via webhook</p>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 size={16} className="animate-spin" />
          <span>Loading workflows...</span>
        </div>
      ) : workflows.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <Workflow size={32} className="mx-auto mb-3 opacity-30" />
          <p>No workflows found</p>
          <p className="text-xs mt-1">Configure N8N_API_KEY to load real workflows</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {workflows.map((wf) => (
            <WorkflowCard key={wf.id} workflow={wf} />
          ))}
        </div>
      )}
    </div>
  )
}
