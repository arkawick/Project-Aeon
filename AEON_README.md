# Aeon — AI-Powered Engineering Operations Workspace

> Every incident your team has ever seen. Every failure that's coming next. One workspace.

"Odysseus for DevOps" — an AI OS for engineering operations combining GitHub Actions, Jenkins, n8n, persistent memory (ChromaDB + Neo4j), and a LangGraph agent for CI/CD root cause analysis, prediction, and automated remediation.

Three AI intelligence features sit on top of that foundation: **Code Provenance** (why is this code the way it is?), **Blast Radius** (what will break if I merge this?), and a **Knowledge Graph** of all incident relationships.

---

## Quick Start

```powershell
cd aeon
docker compose up -d
```

Seed demo data:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Open **http://localhost:3000**

---

## The Demo Flow

### Incident Response (Core)
```
Push to GitHub / Jenkins build runs
        ↓
Aeon Pipelines page shows failure in real time
        ↓
Ask AI: "Why did the Android build fail?"
        ↓
Agent streams live tool calls (search_memory, fetch_logs...)
        ↓
AI returns: root cause + 91% confidence
            + "matches incident #421 from 3 weeks ago"
            + suggested fix
        ↓
Click "Create Issue" → GitHub issue created live
        ↓
Click "Approve PR" → PR created (human in the loop)
        ↓
Incident stored in memory — AI gets smarter for next time
```

### Code Provenance
```
Enter: github repo + file path
        ↓
Aeon traces commit history → linked PRs → linked issues
        ↓
Graph renders: File → Commits → PRs → Issues → Developers
        ↓
AI Evolution Narrative: "Why is this file the way it is today?"
        ↓
Click any commit → see actual diff with added/removed lines
        ↓
Toggle Timeline layout: commits ordered chronologically left→right
```

### Blast Radius
```
Enter: github repo + PR number
        ↓
Aeon fetches all changed files from GitHub
        ↓
Classifies each file: Service / Test / Config / Pipeline / Infra / Dependencies
        ↓
Radial graph: PR center → files → impacted areas
        ↓
AI risk assessment: HIGH / MEDIUM / LOW
        + deploy recommendation
        + "must verify" checklist
```

---

## Architecture

```
              Browser (React + Vite)
                      |
              FastAPI Backend :8000
                      |
      ┌───────────────┼────────────────┐
      ↓               ↓                ↓
  GitHub API      Jenkins API      n8n Webhooks
      │               │
      ↓               ↓
    LangGraph Agent (provider-agnostic: Azure OpenAI or Claude)
              |
    ┌─────────┴─────────┐
    ↓                   ↓
 ChromaDB            Neo4j
(vector recall +   (graph relationships
 re-rank)           + GraphRAG expansion)

AI Intelligence Services (same backend):
  provenance_service.py  →  /api/provenance/stream  (Code Provenance)
  blast_radius_service.py →  /api/blast/stream       (Blast Radius)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11) |
| LLM | **Provider-agnostic** (`core/llm.py`): Azure OpenAI (`gpt-5-mini`) **or** Claude (`claude-sonnet-4-6`); tool-calling on both, mock fallback |
| Agent Framework | LangGraph (StateGraph, astream streaming, provider-agnostic `run_turn()`) |
| Retrieval | Two-stage re-rank (`services/rerank.py`) + GraphRAG (`services/graphrag.py`) |
| Vector Memory | ChromaDB |
| Graph Memory | Neo4j (self-healing connection) |
| Structured DB | PostgreSQL |
| Cache | Redis |
| Frontend | React 18 + Vite + Tailwind CSS |
| Graph Visualization | react-force-graph-2d |
| CI/CD | Jenkins (Docker) + GitHub Actions |
| Workflow Automation | n8n |
| Deployment | Docker Compose (8 services) |

---

## Services

| Service | URL | Credentials |
|---|---|---|
| Frontend | http://localhost:3000 | — |
| Backend API | http://localhost:8000 | — |
| API Docs | http://localhost:8000/docs | — |
| Jenkins | http://localhost:8088 | admin / admin |
| n8n | http://localhost:5678 | — |
| Neo4j | http://localhost:7474 | neo4j / aeon_neo4j |
| ChromaDB | http://localhost:8001 | — |

---

## Project Structure

```
Project-Aeon/
├── aeon/
│   ├── backend/
│   │   ├── main.py
│   │   ├── api/              REST endpoints
│   │   │   ├── pipelines.py, incidents.py, ai.py, memory.py
│   │   │   ├── provenance.py      ← Code Provenance API
│   │   │   ├── blast_radius.py    ← Blast Radius API
│   │   │   └── predict.py         ← Predictive Merge Gate API
│   │   ├── agents/           LangGraph graph + 8 tools
│   │   ├── core/
│   │   │   ├── instances.py  shared singletons
│   │   │   └── llm.py        ← Provider-agnostic LLM (Azure/Anthropic/mock)
│   │   ├── memory/           chroma_store.py + neo4j_store.py (self-healing)
│   │   └── services/
│   │       ├── rerank.py                ← Two-stage retrieval re-rank
│   │       ├── graphrag.py              ← GraphRAG graph expansion
│   │       ├── provenance_service.py   ← GitHub trace + AI narrative
│   │       ├── blast_radius_service.py ← PR impact classifier + AI risk
│   │       └── predict_service.py      ← Merge Gate signal fusion
│   ├── frontend/
│   │   └── src/
│   │       ├── pages/
│   │       │   ├── Dashboard, AIAssistant, Pipelines, Incidents, Workflows
│   │       │   ├── GraphView.jsx      ← Knowledge Graph
│   │       │   ├── Provenance.jsx     ← Code Provenance
│   │       │   ├── BlastRadius.jsx    ← Blast Radius
│   │       │   └── Predict.jsx        ← Predictive Merge Gate
│   │       ├── components/   Sidebar, EventLog, MemoryMatchCard, ActionPanel
│   │       └── lib/          api.js (axios + EventSource clients)
│   ├── jenkins/              Dockerfile + init.groovy.d
│   ├── n8n/                  Workflow definitions
│   ├── docker-compose.yml
│   ├── CODE_PROVENANCE.md    ← Code Provenance feature guide
│   ├── BLAST_RADIUS.md       ← Blast Radius feature guide
│   └── MERGE_GATE.md         ← Predictive Merge Gate feature guide
├── jenkins-setup/
│   ├── jobs/                 10 Jenkinsfile demos
│   ├── create_jobs.py
│   └── README.md
├── github-actions-setup/
│   ├── workflows/            10 workflow YAMLs
│   ├── setup.py
│   └── README.md
├── n8n-setup/                10 workflow JSONs + README
├── reseed.ps1                Restore demo memory after a volume wipe (idempotent)
├── AEON_README.md            ← This file
└── DEMO.md                   90-second demo runbook
```

---

## Frontend Pages

| Page | Route | Purpose |
|---|---|---|
| Dashboard | `/` | Stat cards, recent failures, AI recommendations |
| AI Assistant | `/ai` | Chat with streaming tool calls, confidence scores, memory matches |
| Pipelines | `/pipelines` | Unified GitHub Actions + Jenkins view, auto-refreshes every 30s |
| Incidents | `/incidents` | Semantic search over incident history |
| Workflows | `/workflows` | n8n workflow triggers |
| Knowledge Graph | `/graph` | Force-directed Neo4j visualization — incident patterns |
| Code Provenance | `/provenance` | Trace why any file is the way it is: commits → PRs → issues + AI narrative |
| Blast Radius | `/blast` | Map what breaks if a PR merges: files → services → AI risk assessment |
| Merge Gate | `/predict` | Forecast if a PR's build will fail before it runs — memory + hanging points + PR shape + live CI → PASS/CAUTION/BLOCK |

→ **Full per-page walkthrough** (inputs, flow, API, what you see): `docs/PAGES.md`

---

## AI Intelligence Features

### Code Provenance (`/provenance`)
Traces the full history of any public GitHub file. Fetches commit history → linked PRs → linked issues, generates per-node "why" summaries via Claude, then writes a holistic evolution narrative. Click a commit node to see the real diff. Toggle between force and timeline layouts.

→ Full guide: `aeon/CODE_PROVENANCE.md`

### Blast Radius (`/blast`)
Given any GitHub PR, classifies every changed file (Service / Test / Config / Pipeline / Infrastructure / Dependencies / Docs), infers which services are affected, and asks Claude for a risk level + deploy recommendation. Rendered as a radial graph with PR at center.

→ Full guide: `aeon/BLAST_RADIUS.md`

→ Best demo PR: `expressjs/express` #7233 (dependency upgrade touching 4 categories)

### Predictive Merge Gate (`/predict`)
Forecasts whether a PR's build will fail **before** it runs — no build, just history + live CI. Fuses four signals: incident-memory resemblance to past failures, **hanging points** (targeted per-file co-change — a file changed without a partner it historically changes with), PR shape (source without tests, big diff, dep/lockfile churn), and high-risk file classes. The PR's **existing CI check-runs** act as a ground-truth prior (a failing check forces a high-confidence BLOCK; all-green dampens the estimate). Output: a fail-risk gauge, PASS/CAUTION/BLOCK verdict, confidence level, the specific hanging points, and a "run these before merge" checklist. It **learns**: every forecast is scored against the real build result (matched at `/api/pipelines/ingest`), and the `/predict` page shows a live accuracy scoreboard + calibration. It can also auto-run on a PR-open webhook and post the verdict back as a PR comment + commit status check.

→ Full guide: `aeon/MERGE_GATE.md`

### Knowledge Graph (`/graph`)
Neo4j force-directed graph of all incident relationships — which error types recur, which pipelines share failures, which fixes resolved the same root cause across incidents.

---

## Memory Layer

**Two-stage retrieval** (`services/rerank.py`):
- Stage 1 — wide ChromaDB vector recall (top-10), the agent's own write-backs (`status=analyzed`) excluded so it never grounds on its own past output
- Stage 2 — weighted re-rank: `0.60·cosine + field agreement (error_type / pipeline / source / repo) + recency`; absent context reinforces the semantic signal. Emits human-readable `match_reasons` ("52% semantic", "same error_type") shown on the memory card

**GraphRAG expansion** (`services/graphrag.py`):
- Takes the vector matches as anchors and expands through Neo4j: error type → proven fixes (+ reuse counts) → sibling incidents on other pipelines
- That block is injected into the agent's system prompt, so the model reasons over graph relationships, not just the vector hits

**ChromaDB** — semantic vector store:
- Every incident stored with embeddings of description + logs + root cause
- Persists to `/data` (Chroma 1.x) so memory survives restarts; Code Provenance graphs cached for instant replay

**Neo4j** — relationship graph:
- Incident nodes: `Incident`, `Pipeline`, `ErrorType`, `Fix`; Provenance nodes: `ProvenanceNode` (File, Commit, PR, Issue, Developer)
- Connection **self-heals** the cold-start race (`_ensure_driver`, throttled reconnect) — no manual restart needed
- Visualized on the Knowledge Graph page

---

## LangGraph Agent

8 tools, streaming via `astream()`:

```python
tools = [
    search_chromadb_memory,   # semantic search over past incidents
    query_neo4j_graph,        # relationship traversal
    fetch_github_logs,        # GitHub Actions run logs
    fetch_jenkins_logs,       # Jenkins build console output
    create_github_issue,      # auto-create issues
    create_github_pr,         # suggest PRs (requires human approval)
    trigger_jenkins_build,    # trigger rebuilds
    trigger_n8n_workflow,     # fire n8n automations
]
```

Agent flow:
```
search_memory → call_claude → execute_tools (loop) → synthesize → memory_writer
```

`search_memory` also auto-fetches the failing Jenkins build log (for the job named in the query) to ground the first turn, then runs two-stage retrieval + GraphRAG. `call_claude` uses `llm.run_turn()` — **real tool-calling on either Azure OpenAI or Anthropic** (neutral Anthropic-shaped messages/tools are translated to OpenAI format for Azure). Every analysis is automatically written back to ChromaDB + Neo4j (`memory_writer_node`).

---

## Environment Variables

All in `aeon/backend/.env`:

```env
# --- LLM provider — set ONE (Azure wins if both present); mock works without any ---
# Azure OpenAI (AZURE_OPENAI_ENDPOINT is the FULL chat-completions URL, incl. api-version)
AZURE_OPENAI_ENDPOINT=https://<gateway>/deployments/gpt-5-mini/chat/completions?api-version=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-5-mini
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_API_KEY=...
# ...or Anthropic
ANTHROPIC_API_KEY=sk-ant-...
# Optional: force a provider — azure | anthropic | mock (blank = auto-detect)
LLM_PROVIDER=

GITHUB_TOKEN=ghp_...             # Required for Code Provenance + Blast Radius at depth
GITHUB_ORG=                      # Your GitHub org (leave empty for personal repos)
JENKINS_URL=http://localhost:8080
JENKINS_USER=admin
JENKINS_TOKEN=admin
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=aeon_neo4j
CHROMA_HOST=localhost
CHROMA_PORT=8001
```

After editing `.env` (a recreate is required — `restart` does NOT re-read env_file):
```powershell
docker compose up -d backend
```
Adding Azure needs the `openai` package (already in `requirements.txt`) — rebuild if upgrading an old image: `docker compose build backend`.

---

## Key Design Decisions

- **`core/instances.py`** — shared singletons, no duplicate DB connections
- **Provider-agnostic LLM (`core/llm.py`)** — Azure OpenAI → Anthropic → mock, chosen at runtime; `run_turn()` gives the agent real tool-calling on both providers (Anthropic ⇄ OpenAI message/tool translation), `complete()` serves the single-shot surfaces
- **Two-stage retrieval + GraphRAG** — vector recall re-ranked by field agreement + recency, then expanded through the incident graph so the model reasons over relationships; the agent's own write-backs are excluded from grounding recall
- **SSE streaming everywhere** — AI Assistant, Code Provenance, and Blast Radius all stream progress to the browser via `text/event-stream`; the UI never blocks waiting for a response
- **`memory_writer_node`** — every incident analysis auto-stored, agent improves over time
- **Human-in-the-loop PRs** — issues auto-create, PRs require explicit approval
- **Resilient by design** — Neo4j self-heals the cold-start race (`_ensure_driver`); ChromaDB persists to `/data` so memory survives restarts; `reseed.ps1` restores demo memory after a `down -v`
- **`originalGraph` ref pattern** — ForceGraph2D mutates node objects in place; storing immutable server data separately prevents ghost traces when switching layouts
- **Mock fallback everywhere** — full demo works without any API tokens
- **Jenkins on port 8088** — remapped from 8080 to avoid WSL/Tomcat conflict
