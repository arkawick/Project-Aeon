# Aeon — Complete Setup Guide

> AI-Powered Engineering Operations Workspace  
> Jenkins + GitHub Actions + n8n + ChromaDB + Neo4j + LangGraph Agent

This guide walks you through setting up the entire Aeon stack from scratch — all services, integrations, and demo data.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone the Repo](#2-clone-the-repo)
3. [Environment Variables](#3-environment-variables)
4. [Start All Services](#4-start-all-services)
5. [Seed Demo Data](#5-seed-demo-data)
6. [Jenkins Setup](#6-jenkins-setup)
7. [GitHub Actions Setup](#7-github-actions-setup)
8. [n8n Setup](#8-n8n-setup)
9. [Verify Everything](#9-verify-everything)
10. [Using the App](#10-using-the-app)
11. [Service URLs & Credentials](#11-service-urls--credentials)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

Install these before starting:

| Tool | Version | Download |
|---|---|---|
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop |
| Python | 3.10+ | https://www.python.org/downloads |
| Node.js | 18+ | https://nodejs.org |
| Git | Any | https://git-scm.com |

Make sure Docker Desktop is **running** before proceeding.

---

## 2. Clone the Repo

```powershell
git clone https://github.com/YOUR_USERNAME/Project-Aeon.git
cd Project-Aeon
```

---

## 3. Environment Variables

Copy the example env file and fill in your keys:

```powershell
copy aeon\backend\.env.example aeon\backend\.env
```

Open `aeon/backend/.env` and fill in:

```env
# Required for live AI responses
ANTHROPIC_API_KEY=sk-ant-...

# Required for GitHub pipeline data + issue/PR creation
GITHUB_TOKEN=ghp_...
GITHUB_ORG=                        # leave empty if using a personal account

# Jenkins — pre-configured, no changes needed
JENKINS_URL=http://localhost:8080
JENKINS_USER=admin
JENKINS_TOKEN=admin

# n8n — add after Step 8
N8N_API_KEY=

# Databases — pre-configured, no changes needed
CHROMA_HOST=localhost
CHROMA_PORT=8001
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=aeon_neo4j
```

### Getting your keys

**Anthropic API Key**
1. Go to https://console.anthropic.com
2. API Keys → Create Key → copy it

**GitHub Token**
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token (classic)
3. Select scopes: `repo` and `workflow`
4. Copy the token (`ghp_...`)

> You can skip both keys for now — Aeon has full mock fallbacks and still demonstrates the complete flow.

---

## 4. Start All Services

From the `aeon/` directory:

```powershell
cd aeon
docker compose up -d
```

This starts **8 services** in Docker:

| Service | What it is |
|---|---|
| `backend` | FastAPI Python server (the brain) |
| `frontend` | React + Vite app |
| `jenkins` | CI/CD server with 5 pre-seeded jobs |
| `n8n` | Workflow automation |
| `chromadb` | Vector memory store |
| `neo4j` | Graph memory store |
| `postgres` | Incident database |
| `redis` | Cache |

Wait about **60 seconds** for all services to fully start (Neo4j and Jenkins take the longest).

Check all containers are running:

```powershell
docker compose ps
```

All services should show `Up`.

---

## 5. Seed Demo Data

This loads 5 pre-built incidents into ChromaDB and Neo4j so the AI has memory to work with from the start:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

You should see a response like:
```json
{"seeded": 5, "chromadb_stored": 5, "neo4j_stored": 5}
```

Open **http://localhost:3000** — the dashboard should load with stat cards and pipeline data.

---

## 6. Jenkins Setup

Jenkins starts automatically with 5 demo pipeline jobs pre-seeded. No extra steps needed.

**Access Jenkins:** http://localhost:8088  
**Login:** `admin` / `admin`

> Port is **8088**, not 8080 — 8080 is commonly occupied by other services.

### Pre-loaded Jobs

| Job | Simulates | Result |
|---|---|---|
| `frontend-build` | Node.js/Vite build | Fails — missing path alias |
| `backend-tests` | Maven integration tests | Fails — OutOfMemoryError |
| `android-build` | Gradle APK build | Fails — androidx.core conflict |
| `docker-image-build` | Docker image build | Fails — disk full |
| `deploy-staging` | Kubernetes staging deploy | Passes |

Each job runs once on first boot and automatically notifies Aeon via webhook.

### Re-seed Jenkins jobs (only if you wiped Docker volumes)

If you ran `docker compose down -v` and lost data:

```powershell
pip install requests
python jenkins-setup/create_jobs.py
```

This recreates all 5 jobs and triggers their first builds.

---

## 7. GitHub Actions Setup

This connects real GitHub Actions runs to Aeon using a public tunnel.

### Step 1 — Install dependencies

```powershell
pip install requests PyNaCl
```

### Step 2 — Run the setup script

Make sure Aeon is running (`docker compose up -d`), then:

```powershell
cd github-actions-setup
python setup.py --token ghp_YOUR_TOKEN --repo aeon-demo
```

This script automatically:
1. Starts a localtunnel → creates a public URL for `localhost:8000`
2. Creates a GitHub repo called `aeon-demo` under your account
3. Adds `AEON_URL` as an encrypted repo secret
4. Pushes 5 workflow YAML files to `.github/workflows/`
5. Triggers the first runs

### Step 3 — Keep the tunnel running

The terminal running `setup.py` must stay open. GitHub Actions can only reach Aeon while the tunnel is active.

### What you get

Within 2-3 minutes of the script finishing:
- 5 workflow runs appear in your GitHub repo under Actions
- Those runs show up in Aeon → Pipelines in real time

**Workflows:**

| Workflow | Result |
|---|---|
| `frontend-build.yml` | Fails — missing Vite path alias |
| `backend-tests.yml` | Fails — OOM in integration tests |
| `android-build.yml` | Fails — androidx.core conflict |
| `docker-image-build.yml` | Fails — disk full |
| `deploy-staging.yml` | Passes |

---

## 8. n8n Setup

n8n is the workflow automation layer. Aeon triggers n8n workflows when incidents are detected.

### Step 1 — Create your n8n account

1. Open **http://localhost:5678**
2. Sign up with any email + password (local only, no external verification)
3. Skip the questionnaire

### Step 2 — Get an API key

1. In n8n: click your avatar (bottom-left) → **Settings** → **API**
2. Click **Create an API key** → copy it

### Step 3 — Import workflows

```powershell
cd n8n-setup
python import_workflows.py --api-key YOUR_N8N_API_KEY
```

This imports and activates 2 workflows:

| Workflow | What it does |
|---|---|
| `CI Failure → Slack Notification` | Sends a formatted Slack alert when a build fails |
| `Incident → GitHub Issue` | Auto-creates a GitHub issue with root cause analysis |

You'll see output like:
```
Importing: CI Failure → Slack Notification
  Created (id=abc123)
  Activated
  Webhook URL: http://localhost:5678/webhook/aeon-ci-failure

Importing: Incident → GitHub Issue
  Created (id=def456)
  Activated
  Webhook URL: http://localhost:5678/webhook/aeon-incident
```

### Step 4 — Add API key to Aeon

Open `aeon/backend/.env` and set:
```env
N8N_API_KEY=your_key_here
```

Restart the backend to pick up the change:
```powershell
docker compose restart backend
```

### Step 5 (Optional) — Add Slack notifications

To get real Slack alerts from the CI Failure workflow:

1. Go to https://api.slack.com/apps → Create New App → From scratch
2. Name it `Aeon Alerts`, choose your workspace
3. Incoming Webhooks → Activate → Add New Webhook → choose a channel → copy the URL
4. In n8n: Credentials → Add → search `Slack` → Webhook-Based → paste URL → name it `Slack Aeon`
5. Open the `CI Failure → Slack Notification` workflow → click the Slack node → set credential to `Slack Aeon`

---

## 9. Verify Everything

### Check all services

| Service | URL | Expected |
|---|---|---|
| Frontend | http://localhost:3000 | Dashboard loads |
| Backend health | http://localhost:8000/health | `{"status":"ok"}` |
| API docs | http://localhost:8000/docs | Swagger UI |
| Jenkins | http://localhost:8088 | Login page (admin/admin) |
| n8n | http://localhost:5678 | Workflow list |
| Neo4j browser | http://localhost:7474 | Graph browser |
| ChromaDB | http://localhost:8001/api/v1/heartbeat | `{"nanosecond heartbeat": ...}` |

### Check memory is seeded

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/status
```

Should return something like:
```json
{
  "chromadb": {"connected": true, "incident_count": 5},
  "neo4j": {"connected": true, "top_error_types": [...]}
}
```

---

## 10. Using the App

Open **http://localhost:3000**

### Dashboard (`/`)
- Stat cards: total pipelines, active incidents, success rate
- Recent pipeline failures
- AI recommendations from incident history
- n8n workflows with Trigger buttons

### Pipelines (`/pipelines`)
- Unified view of Jenkins jobs + GitHub Actions runs
- Tabs to filter by source
- Pipeline names are clickable links → open the actual Jenkins/GitHub build
- Auto-refreshes every 30 seconds

### AI Assistant (`/ai`)

This is the core of Aeon. Type a query like:

```
Why did the Android Gradle build fail?
```

Watch it:
1. Search ChromaDB memory for similar past incidents
2. Stream live tool calls (search_memory, fetch_logs...)
3. Return: root cause + confidence score + memory match ("seen 3 weeks ago")
4. Offer actions: Create GitHub Issue, Approve PR

Click **Execute** to auto-create a GitHub issue.  
Click **Approve & Create PR** to create a fix PR (requires your approval — human in the loop).

### Incidents (`/incidents`)
- Semantic search over all stored incidents
- Search by symptoms, not exact keywords

### Workflows (`/workflows`)
- List of n8n workflows with active/inactive status
- Trigger any workflow manually

### Knowledge Graph (`/graph`)
- Force-directed graph of all incidents, pipelines, error types, and fixes
- Shows patterns: "These 2 Android incidents share the same error type and fix"

---

## 11. Service URLs & Credentials

| Service | URL | Credentials |
|---|---|---|
| Aeon Frontend | http://localhost:3000 | — |
| Aeon Backend | http://localhost:8000 | — |
| API Docs (Swagger) | http://localhost:8000/docs | — |
| Jenkins | http://localhost:8088 | admin / admin |
| n8n | http://localhost:5678 | your email/password |
| Neo4j Browser | http://localhost:7474 | neo4j / aeon_neo4j |
| ChromaDB | http://localhost:8001 | — |

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `docker compose up` fails | Make sure Docker Desktop is running |
| Jenkins not loading | Use port **8088**, not 8080 |
| Jobs not in Jenkins | Wait 60s after first boot — then run `python jenkins-setup/create_jobs.py` |
| Pipelines page empty | Run `docker compose restart backend` |
| AI returns mock responses | Set `ANTHROPIC_API_KEY` in `.env` and restart backend |
| GitHub pipelines not showing | Set `GITHUB_TOKEN` in `.env` and restart backend |
| Memory search returns nothing | Re-run `Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post` |
| Knowledge Graph empty | Seed memory first, then refresh the graph page |
| n8n workflows not in Aeon | Set `N8N_API_KEY` in `.env` and run `docker compose restart backend` |
| GitHub Actions not appearing | Tunnel must be running — re-run `python github-actions-setup/setup.py` |
| `PyNaCl` install fails on Windows | Install Visual C++ Build Tools first, then `pip install PyNaCl` |
| Port conflict on 8080 | Already remapped — use 8088 for Jenkins |

### Reset everything

To wipe all data and start fresh:

```powershell
cd aeon
docker compose down -v
docker compose up -d
```

Then re-run Step 5 (seed data) and Step 6 (re-seed Jenkins jobs).

### Restart a single service

```powershell
docker compose restart backend
docker compose restart frontend
docker compose restart jenkins
```

---

## How It All Fits Together

```
Your browser (http://localhost:3000)
        |
        | HTTP / SSE
        ↓
FastAPI Backend (port 8000)
        |
   ┌────┴─────────────────────────────┐
   ↓                ↓                 ↓
GitHub API      Jenkins API      n8n Webhooks
(live runs)     (live jobs)    (CI failure alerts)
   |                |
   └────────┬───────┘
            ↓
     LangGraph Agent
   (8 tools, streaming)
            |
      ┌─────┴──────┐
      ↓            ↓
  ChromaDB       Neo4j
(vector search) (graph memory)
"Find similar   "This error was
 past incidents" fixed 3 times"
```

**The memory loop:**
1. Jenkins/GitHub builds fail → Aeon ingests the logs
2. AI Assistant searches ChromaDB (semantic) + Neo4j (relationships)
3. Agent returns: root cause + confidence + "matches incident from 3 weeks ago"
4. You approve → GitHub issue/PR created
5. Analysis is written back to both memory stores
6. Next time a similar failure happens, Aeon recognizes it instantly
