# Aeon — AI-Powered Engineering Operations Workspace

> Every incident your team has ever seen. Every failure that's coming next. One workspace.

"Odysseus for DevOps" — an AI OS for engineering operations combining GitHub Actions, Jenkins, n8n, persistent memory (ChromaDB + Neo4j), and a LangGraph agent for CI/CD root cause analysis, prediction, and automated remediation.

---

## Quick Start

```powershell
cd aeon
docker compose up -d
```

Then seed demo data:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Open **http://localhost:3000**

---

## The Demo Flow

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

---

## Architecture

```
              Browser (React + Vite)
                      |
              FastAPI Backend :8000
                      |
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
    GitHub API    Jenkins API    n8n Webhooks
        ↓             ↓             ↓
              LangGraph Agent
              (Claude claude-sonnet-4-6)
                      |
          ┌───────────┴───────────┐
          ↓                       ↓
       ChromaDB               Neo4j
    (vector search)       (graph relationships)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| LLM | Claude API (`claude-sonnet-4-6`) via AsyncAnthropic |
| Agent Framework | LangGraph (StateGraph, astream streaming) |
| Vector Memory | ChromaDB |
| Graph Memory | Neo4j |
| Structured DB | PostgreSQL |
| Cache | Redis |
| Frontend | React 18 + Vite + Tailwind CSS |
| Graph Visualization | react-force-graph-2d |
| CI/CD | Jenkins (Docker) + GitHub Actions |
| Workflow Automation | n8n |
| Deployment | Docker Compose (8 services) |

---

## Services

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | Main app |
| Backend API | http://localhost:8000 | FastAPI |
| API Docs | http://localhost:8000/docs | Swagger |
| Jenkins | http://localhost:8088 | admin/admin (port 8088 — 8080 blocked by WSL) |
| n8n | http://localhost:5678 | Workflow automation |
| Neo4j | http://localhost:7474 | neo4j/aeon_neo4j |
| ChromaDB | http://localhost:8001 | Vector store |

---

## Project Structure

```
Project-Aeon/
├── aeon/
│   ├── backend/
│   │   ├── main.py
│   │   ├── api/              REST endpoints (pipelines, incidents, ai, memory, ...)
│   │   ├── agents/           LangGraph graph + 8 tools
│   │   ├── core/             instances.py — shared singletons
│   │   ├── memory/           chroma_store.py + neo4j_store.py
│   │   └── services/         GitHub, Jenkins, n8n clients
│   ├── frontend/
│   │   └── src/
│   │       ├── pages/        Dashboard, AIAssistant, Pipelines, Incidents, Workflows, GraphView
│   │       ├── components/   Sidebar, EventLog, MemoryMatchCard, ActionPanel, ConfidenceBar
│   │       └── lib/          api.js (axios client)
│   ├── jenkins/              Dockerfile + init.groovy.d (5 auto-seeded jobs)
│   ├── n8n/                  Workflow definitions
│   └── docker-compose.yml    All 8 services
├── jenkins-setup/
│   ├── jobs/                 Jenkinsfile.frontend/backend/android/docker/deploy
│   ├── create_jobs.py        Python script — seeds jobs via Jenkins REST API
│   ├── seed-jobs.groovy      Job DSL seed script
│   └── README.md
├── github-actions-setup/
│   ├── workflows/            5 workflow YAMLs (frontend/backend/android/docker/deploy)
│   ├── setup.py              One-command real GitHub integration setup
│   └── README.md
├── docs/
│   ├── RUNNING.md            How to start, stop, rebuild
│   ├── SERVICES.md           All URLs, ports, credentials
│   ├── DATABASES.md          Inspecting databases from terminal
│   └── GRAPHIFY.md           Knowledge Graph page guide
├── AEON_README.md            This file
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

---

## Memory Layer

**ChromaDB** — semantic vector search:
- Every incident stored with embeddings of description + logs + root cause
- `search_similar(query, top_k=3)` returns nearest incidents
- Used by the agent's `search_chromadb_memory` tool

**Neo4j** — relationship graph:
- Nodes: `Incident`, `Pipeline`, `ErrorType`, `Fix`
- Edges: `CAUSED_BY`, `HAS_ERROR`, `RESOLVED_BY`, `FIXED_BY`
- Enables: "This exact error type was fixed the same way 3 times"
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

Every analysis is automatically written back to ChromaDB + Neo4j (`memory_writer_node`).

---

## GitHub Actions Integration

Real integration using localtunnel (free, no account needed):

```powershell
cd github-actions-setup
pip install requests PyNaCl
python setup.py --token ghp_YOUR_TOKEN --repo aeon-demo
```

This creates the GitHub repo, sets the `AEON_URL` secret, and pushes all 5 workflow files. See `github-actions-setup/README.md` for details.

---

## Jenkins Integration

Jenkins runs in Docker and starts with 5 pre-seeded jobs. To re-seed after data wipe:

```powershell
pip install requests
python jenkins-setup/create_jobs.py
```

See `jenkins-setup/README.md` for full details.

---

## Environment Variables

All in `aeon/backend/.env` (copy from `.env.example`):

```env
ANTHROPIC_API_KEY=sk-ant-...     # Required for live AI (mock works without it)
GITHUB_TOKEN=ghp_...             # For GitHub API (issue/PR creation, workflow runs)
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

After editing `.env`:
```powershell
docker compose up -d --force-recreate backend
```

---

## Key Design Decisions

- **`core/instances.py`** — shared singletons, no duplicate DB connections
- **`AsyncAnthropic` + `messages.stream()`** — per-token SSE to the browser
- **`memory_writer_node`** — every analysis auto-stored, agent improves over time
- **Human-in-the-loop PRs** — issues auto-create, PRs require explicit approval
- **Mock fallback everywhere** — full demo works without any API tokens
- **`VITE_API_URL=http://backend:8000`** — Vite proxy uses Docker service name, not localhost
- **Jenkins on port 8088** — remapped from 8080 to avoid WSL/Tomcat conflict
