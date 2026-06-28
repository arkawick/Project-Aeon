import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

// AI
export async function analyzeBuild(query, context = {}, opts = {}) {
  const { data } = await api.post('/ai/analyze', { query, context, ...opts })
  return data
}

export function streamAnalysis(query) {
  const url = `/api/ai/stream?query=${encodeURIComponent(query)}`
  return new EventSource(url)
}

export function streamResearch(query) {
  const url = `/api/ai/research/stream?query=${encodeURIComponent(query)}`
  return new EventSource(url)
}

export async function generatePostmortem(analysis, query = '') {
  const { data } = await api.post('/ai/postmortem', { analysis, query })
  return data.markdown
}

// Actions
export async function executeActions(analysis, incident_id, opts = {}) {
  const { data } = await api.post('/actions/execute', { analysis, incident_id, ...opts })
  return data
}

export async function getPendingActions() {
  const { data } = await api.get('/actions/pending')
  return data
}

export async function approveAction(action_id) {
  const { data } = await api.post(`/actions/${action_id}/approve`)
  return data
}

export async function rejectAction(action_id, reason = '') {
  const { data } = await api.post(`/actions/${action_id}/reject`, { reason })
  return data
}

// Pipelines
export async function getPipelines() {
  const { data } = await api.get('/pipelines/')
  return data
}

// Incidents
export async function getIncidents() {
  const { data } = await api.get('/incidents/')
  return data
}

export async function searchIncidents(q, top_k = 5) {
  const { data } = await api.get(`/incidents/similar?q=${encodeURIComponent(q)}&top_k=${top_k}`)
  return data
}

// Workflows
export async function getWorkflows() {
  const { data } = await api.get('/n8n/workflows')
  return data
}

export async function triggerWorkflow(id, payload = {}) {
  const { data } = await api.post(`/n8n/workflows/${id}/trigger`, { payload })
  return data
}

// Integrations
export async function getIntegrationsStatus() {
  const { data } = await api.get('/integrations/status')
  return data
}

// Memory
export async function seedMemory() {
  const { data } = await api.post('/memory/seed')
  return data
}

export async function getMemoryStatus() {
  const { data } = await api.get('/memory/status')
  return data
}

// GitHub
export async function createIssue(repo, title, body) {
  const { data } = await api.post('/github/issues', { repo, title, body })
  return data
}

export async function createPR(repo, title, body, branch) {
  const { data } = await api.post('/github/prs', { repo, title, body, branch })
  return data
}

// Odysseus
export async function getOdysseusStatus() {
  const { data } = await api.get('/odysseus/status')
  return data
}

export async function startOdysseusResearch(query) {
  const { data } = await api.post('/odysseus/research/start', { query })
  return data
}

export default api
