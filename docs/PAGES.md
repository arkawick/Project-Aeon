# How every page works

A walkthrough of each page in the Aeon UI (`http://localhost:3000`): what it answers, what you type, what happens under the hood, and which API it calls. The sidebar groups pages into **Core Ops** and **AI Intelligence**, plus an external **Odysseus Research** link.

Every AI/graph surface follows two rules:
- **Streaming (SSE):** long-running pages (`AI Assistant`, `Provenance`, `Blast Radius`, `Co-Change`, `Merge Gate`) open an `EventSource` to a `/stream` endpoint and render `{type: step | result | ...}` events live — the UI never blocks on a spinner.
- **Mock fallback:** every page returns demo-quality data even with no API tokens or a service down, so nothing ever hard-errors in a demo.

The frontend API client is `aeon/frontend/src/lib/api.js`; the backend routers are under `aeon/backend/api/` (all mounted at `/api`).

---

## Core Ops

### Dashboard — `/`
**Answers:** "Is everything wired, and what's happening right now?"

The landing page. On load it pulls integration health, recent pipeline activity, and memory counts, and renders stat cards + a recent-failures list + AI recommendations. A **Seed demo data** action is available here (or via the API) to load the demo incidents.

- **API:** `GET /api/integrations/status` (per-service live/mock health), `GET /api/pipelines/` (recent builds), `GET /api/memory/status` (ChromaDB/Neo4j counts), `POST /api/memory/seed`.
- **What you see:** integration status chips (GitHub, Jenkins, n8n, ChromaDB, Neo4j, **AI (LLM)** with its active provider, Odysseus), recent pipeline runs, memory size.

### AI Assistant — `/ai`
**Answers:** "Why did this build fail — and what's the fix?" (the flagship surface)

Type a question (e.g. *"Why did the Android Gradle build fail?"*). A **provider-agnostic LangGraph agent** runs live: it searches incident memory, **auto-fetches the failing Jenkins log** for the referenced job, calls tools (logs, memory, graph, issue/PR), and streams its reasoning token-by-token. Two modes: **Quick Analysis** and **Deep Research** (more tool calls, richer report).

- **Flow:** `search_memory` (two-stage rerank + GraphRAG) → `call_claude` (`llm.run_turn`, Azure **or** Anthropic) ⇄ `execute_tools` → `synthesize` → `memory_writer` (writes the analysis back so the agent improves).
- **API:** `GET /api/ai/stream?query=` and `GET /api/ai/research/stream?query=` (SSE); `POST /api/ai/postmortem` (one-click post-mortem `.md`); action engine `POST /api/actions/execute`, `/actions/{id}/approve|reject`.
- **What you see:** a live "thinking" log (tool calls, memory search), a streaming answer, then a result card — **root cause**, confidence bar, a **memory-match card** (`inc_seed_003 · 1 month ago · 52%` with "why it matched" chips), suggested fix, similar-incident chips, and an **Action Panel** (enter repo → issue auto-creates; **PR requires an explicit approve click**). Buttons: Generate Post-mortem, Research deeper in Odysseus.
- **Fallback:** with no LLM key it returns a convincing scripted analysis; with a key it truly reasons over your query + logs.

### Pipelines — `/pipelines`
**Answers:** "What's the state of all my builds, across systems?"

A unified view of **GitHub Actions + Jenkins** runs in one list, colour-coded by status, auto-refreshing every 30s. Failed builds that were pushed to Aeon (via the CI `Notify Aeon` step) also appear here and are indexed into memory.

- **API:** `GET /api/pipelines/` — merges live GitHub workflow runs + Jenkins jobs + webhook-ingested events. Webhooks arrive at `POST /api/pipelines/ingest`.
- **What you see:** rows with source (GitHub/Jenkins), job/workflow name, status, branch, duration, and links back to the CI system.

### Incidents — `/incidents`
**Answers:** "Have we seen anything like this before?"

Browse and **semantically search** the incident memory — the same ChromaDB store the AI Assistant writes back to. Type a symptom and it returns the nearest past incidents by meaning, not keywords.

- **API:** `GET /api/incidents/` (list), `GET /api/incidents/similar?q=&top_k=` (vector search). Each incident carries root cause, fix, error type, pipeline, severity.
- **What you see:** incident cards with similarity, root cause, and fix; expandable rows (with a "Research in Odysseus" option).

### Workflows — `/workflows`
**Answers:** "What automations do I have, and can I fire one?"

Lists the **n8n** workflows and lets you trigger them from the dashboard (e.g. a Slack/Teams notification, auto-deploy, rollback).

- **API:** `GET /api/n8n/workflows`, `POST /api/n8n/workflows/{id}/trigger`.
- **What you see:** workflow cards (active/inactive) with a trigger button.
- **Fallback:** without an n8n API key it shows mock workflows; Slack/Jira-node workflows can't activate without their credentials (expected).

---

## AI Intelligence

### Knowledge Graph — `/graph`
**Answers:** "How do our incidents, error types, and fixes relate?"

A force-directed **Neo4j** visualization of the incident knowledge graph — which error types recur, which pipelines share failures, which fixes resolved the same root cause across incidents.

- **API:** `GET /api/memory/graph` (nodes + edges from Neo4j; falls back to a mock graph if Neo4j is empty).
- **Node types:** `Incident`, `Pipeline`, `ErrorType`, `Fix` (+ `ProvenanceNode` from the Provenance feature).
- **What you see:** an interactive graph; click a node for details. *(If you ever see foreign nodes here, it's cross-project pollution on the shared Neo4j — see CLAUDE.md.)*

### Code Provenance — `/provenance`
**Answers:** "Why is this file the way it is today?"

Enter a public **repo + file path**. Aeon traces the file's commit history → linked PRs → linked issues, generates per-node "why" summaries, and writes a holistic evolution narrative. Click a commit to see the real diff; toggle a chronological timeline layout.

- **Flow:** one GraphQL request when `GITHUB_TOKEN` is set (fast); parallel REST fallback otherwise. AI "why" + narrative run concurrently. Graphs are cached in Neo4j for instant replay.
- **API:** `GET /api/provenance/stream?repo=&file_path=&max_commits=` (SSE), `GET /api/provenance/diff?repo=&sha=`, `GET /api/provenance/cached`.
- **Demo:** `expressjs/express` + `lib/application.js` (~2s with a token).

### Blast Radius — `/blast`
**Answers:** "If I merge this PR, what breaks?"

Enter a **repo + PR number**. Aeon classifies every changed file (Service / Test / Config / Pipeline / Infra / Dependencies / Docs), maps impacted services, recalls related past incidents from memory, and asks the LLM for a **HIGH/MEDIUM/LOW** risk + deploy recommendation. Rendered as a radial graph (PR → files → impact).

- **API:** `GET /api/blast/stream?repo=&pr=` (SSE — steps, a `memory` event, a `risk` event, then the graph).
- **Demo:** `expressjs/express` PR `7233` — recalls `inc_demo_421` at ~0.78. Full guide: `aeon/BLAST_RADIUS.md`.

### Co-Change — `/cochange`
**Answers:** "Which files always change together?"

Enter a **repo** (+ optional focus file / commit depth). Aeon mines recent commit history for file pairs that keep changing in the same commit — **hidden coupling** no import graph shows — scored `co / min(a, b)`, and adds an AI insight.

- **API:** `GET /api/cochange/stream?repo=&commits=&file_path=` (SSE — steps, an `insight` event, then a force graph).
- **Demo:** `expressjs/express`, 100 commits. Full guide: `aeon/COCHANGE.md`.

### Merge Gate — `/predict`
**Answers:** "Is this PR's build going to fail — *before* I run it?"

Enter a **repo + PR number**. Aeon fuses four signals — incident-memory resemblance, **hanging points** (per-file co-change: a file changed without a partner it historically moves with), PR shape (source-without-tests / big diff / deps), and risk file classes — plus the PR's **live CI check state** as a ground-truth prior, into a **PASS / CAUTION / BLOCK** forecast with a confidence level.

It also **learns**: every forecast is scored against the real build outcome (matched at `/api/pipelines/ingest`), shown as a live accuracy scoreboard; and it can **post the verdict back to the PR** (comment + commit status).

- **API:** `GET /api/predict/stream?repo=&pr=&commits=` (SSE), `GET /api/predict/stats` (learning scoreboard), `POST /api/predict/post?repo=&pr=` (post to PR — needs write token), `POST /api/predict/webhook` (auto-run on PR events).
- **What you see:** a fail-risk **gauge**, verdict + **confidence** chip, live **CI status**, a four-bar **signal breakdown**, **hanging points**, **past incidents it resembles**, a **"run these before merge"** checklist, a **"Gate learning"** accuracy card, and a **"Post verdict to PR"** button.
- **Demo:** `expressjs/express` PR `7233` → **PASS 25%** (it's a merged PR whose CI passed, so the ground-truth prior overrides the historical resemblance — the gate is honest). For a BLOCK/CAUTION beat, use an open PR whose CI hasn't passed. Full guide: `aeon/MERGE_GATE.md`.

---

## Extended Workspace

### Odysseus Research — external link (`http://localhost:7000`)
Not an Aeon page — a linked deep-research workspace. The sidebar shows a live status dot; buttons on the AI Assistant and Incidents pages hand an analysis off to Odysseus for deeper investigation.

- **API:** `GET /api/odysseus/status` (the dot), `POST /api/odysseus/research/start` (proxied hand-off). Aeon works fully without Odysseus running.

---

## Quick reference

| Page | Route | Primary endpoint | Streaming |
|---|---|---|---|
| Dashboard | `/` | `/api/integrations/status`, `/api/pipelines/` | no |
| AI Assistant | `/ai` | `/api/ai/stream`, `/api/ai/research/stream` | **SSE** |
| Pipelines | `/pipelines` | `/api/pipelines/` | no (30s poll) |
| Incidents | `/incidents` | `/api/incidents/`, `/api/incidents/similar` | no |
| Workflows | `/workflows` | `/api/n8n/workflows` | no |
| Knowledge Graph | `/graph` | `/api/memory/graph` | no |
| Code Provenance | `/provenance` | `/api/provenance/stream` | **SSE** |
| Blast Radius | `/blast` | `/api/blast/stream` | **SSE** |
| Co-Change | `/cochange` | `/api/cochange/stream` | **SSE** |
| Merge Gate | `/predict` | `/api/predict/stream` (+ `/stats`, `/post`, `/webhook`) | **SSE** |

Full API surface is browsable at **http://localhost:8000/docs**.
