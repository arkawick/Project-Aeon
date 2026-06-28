# Aeon — Demo Runbook

> Story: Broken build → AI diagnoses with memory → AI fixes → deep research → Odysseus handoff.

---

## 1. Start Everything (2 min before demo)

```powershell
# Aeon stack
cd aeon
docker compose up -d

# Odysseus (optional but impressive)
cd ../odysseus-setup
docker compose up -d

# Ollama (for Odysseus AI features)
ollama serve
```

Wait ~30 seconds, then seed memory:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Open **http://localhost:3000** and verify:
- Dashboard loads with stat cards
- No red errors in browser console

**All services:**

| Service | URL | Status check |
|---|---|---|
| Frontend | http://localhost:3000 | Opens in browser |
| Backend | http://localhost:8000/health | Returns `{"status":"ok"}` |
| Jenkins | http://localhost:8088 | admin / admin |
| n8n | http://localhost:5678 | Opens in browser |
| Neo4j | http://localhost:7474 | neo4j / aeon_neo4j |
| Odysseus | http://localhost:7000 | admin / aeon_demo |

---

## 2. Demo Flow

### Step 1 — Dashboard (15s)
> "This is Aeon — our DevOps AI workspace. It shows active incidents, pipeline failures, and AI recommendations in real time."

Point at:
- Stat cards (open incidents, pipeline health, memory count)
- Recent failures in the pipeline list
- n8n workflows card at the bottom

### Step 2 — Pipelines page (15s)
> "Every build from Jenkins and GitHub Actions shows up here unified."

Navigate to **Pipelines**:
- Jenkins jobs: `frontend-build`, `backend-tests`, `android-build`, `docker-image-build`, `deploy-staging`
- Clickable job names open directly in Jenkins/GitHub
- Filter by source with the tabs

### Step 3 — AI Assistant, Quick Analysis (40s)
> "Let me ask Aeon why the Android build failed."

Make sure mode is set to **Quick Analysis** (top right). Type:
```
Why did the Android Gradle build fail? It's throwing dependency conflicts.
```

Watch live as it streams:
1. **EventLog**: "Searching incident memory..." → "Found strong match: inc_seed_003 (3 weeks ago)"
2. **Thinking bubble** shows Claude typing token by token
3. **Analysis card** appears:
   - Root cause (red box)
   - **Confidence bar** ~91% (green)
   - **Memory match**: "inc_seed_003 · 3 weeks ago · 94% similar"
   - Suggested fix (code block)

> "Notice — it says 'This matches incident inc_seed_003 from 3 weeks ago'. That's the memory layer. It's seen this Gradle conflict before and knows the fix."

### Step 4 — Execute Actions (15s)
> "Now let's fix it."

Type repo: `acme/android-app` → click **Execute**

- GitHub issue created instantly (green badge)
- PR proposal appears (yellow): "Awaiting Approval"

> "It creates the issue automatically, but asks me to approve the PR. Human in the loop — Aeon never merges without permission."

Click **Approve & Create PR** → "PR Created ✓"

### Step 5 — Deep Research mode (30s)
> "That was a quick diagnosis. Now let me show you Deep Research — a full investigation."

Switch mode toggle to **Deep Research**. Type:
```
Investigate the recurring Android build failures this sprint — what's the pattern?
```

Watch:
- Up to 15 tool call iterations
- Richer result: Executive Summary, Contributing Factors, Impact, Resolution, Action Items

> "Deep Research runs 15 iterations — it searches memory, queries the graph, fetches logs, and synthesizes a proper incident investigation report."

Click **Generate Post-mortem** → full markdown report appears with Copy and Download buttons.

### Step 6 — Odysseus handoff (20s)
> "Now here's the extended workspace integration."

Click **"Research deeper in Odysseus"** on the analysis result.

- Aeon calls Odysseus's API, starts a research session, opens it in a new tab
- Show the Aeon sidebar — **Extended Workspace** section with Odysseus status dot (green if running)

> "Odysseus is a self-hosted AI workspace. Aeon hands off context directly — research continues there with Ollama running locally."

### Step 7 — Knowledge Graph (optional, 20s)
> "Every incident is stored as a knowledge graph. These two Android incidents connect to the same error type and fix — Aeon recognized the pattern automatically."

Navigate to **Knowledge Graph** → force-directed graph with color-coded nodes:
- Orange = Incident
- Yellow = ErrorType
- Green = Fix

---

## 3. Judge Q&A Prep

**"What makes this different from just calling ChatGPT on the logs?"**
> The memory layer. When Aeon sees a failure, it searches every incident the team has ever seen and says "this matches incident #421 from 3 weeks ago, fixed by clearing the Gradle cache." A raw LLM starts fresh every time. Aeon gets smarter with every incident it processes — the `memory_writer_node` runs after every query.

**"How does the memory work technically?"**
> Two stores: ChromaDB for semantic vector search (finds similar log patterns by embedding similarity), and Neo4j for relationship graphs (tracks which errors appear in which pipelines and what fixes worked). Every analysis is automatically written back to both.

**"Is this running real AI or mocked?"**
> The agent is a real LangGraph graph calling Claude Sonnet 4.6 via the Anthropic API. You can watch the live tool calls streaming in the UI — `search_chromadb_memory`, `fetch_github_logs`, etc. GitHub/Jenkins fall back to mock data if tokens aren't configured, but the AI reasoning is always live.

**"What's Odysseus?"**
> Odysseus is a separate open-source self-hosted AI workspace. Aeon integrates with it as an extended workspace — when you need deeper research, chat history, or documents beyond CI/CD context, Aeon hands off the query to Odysseus running locally with Ollama.

**"Could this work in production?"**
> The architecture is production-ready: async FastAPI, ChromaDB + Neo4j as persistent stores, SSE for real-time streaming, Docker Compose for deployment. The human-in-the-loop PR approval keeps engineers in control. Main gap: ChromaDB and Neo4j would need clustering for large orgs.

---

## 4. Fallback (if something breaks)

| Problem | Fix |
|---|---|
| Pipelines page empty | `docker compose restart frontend` |
| Backend not responding | `docker compose restart backend` |
| AI returns mock data | Set `ANTHROPIC_API_KEY` in `aeon/backend/.env`, restart backend |
| Memory empty | `Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post` |
| Jenkins not loading | Use port **8088** — not 8080 (8080 blocked by WSL) |
| Knowledge Graph empty | Seed memory first, then Refresh on graph page |
| Odysseus offline | Sidebar dot turns grey — all Aeon features still work |
| Odysseus "Research" button does nothing | Check `docker compose ps` in `odysseus-setup/` |

**Nuclear fallback:** mock data path shows the full demo flow without any credentials. Memory match card, confidence bar, streaming text, and action panel all appear with mock data.
