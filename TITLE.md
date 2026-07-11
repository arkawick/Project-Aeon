<!-- ======================================================================
     PROJECT AEON  —  A3 JURY POSTER  (297 × 420 mm, portrait)
     Single page. Display / print at A3.
     ====================================================================== -->

<div align="center">

# ⧗ AEON

## **A**utonomous **E**ngineering **O**perations **N**exus

### *The DevOps AI that **remembers**.*

> *aeon (n.) — an immense span of time.*
> **Your infrastructure should never make the same mistake twice.**

</div>

---

## 🎯 Problem Statement

Every engineering team loses hours to the **same** CI/CD failures. A build breaks, an on-call engineer digs through logs, finds the root cause, fixes it — **and the knowledge evaporates.** Three weeks later a teammate hits the identical failure and starts from zero. Existing LLM tools only *summarize a single log* — they have **no memory**, so every incident is treated as brand new.

## 💡 Our Solution

**AEON is a persistent memory layer for your DevOps stack.** It plugs into GitHub, Jenkins & n8n, uses a **LangGraph + Claude** agent to diagnose every pipeline failure, and **writes every diagnosis back into a searchable incident memory (vector + graph).** The next failure is met with:

> ### *"This matches incident #421 from 3 weeks ago — same Gradle conflict. Here's the fix that worked."*

**The differentiator is incident memory — not log summarization. AEON gets smarter every time it is used.**

---

## 🧠 Core Loop

<div align="center">

**BROKEN BUILD → AI DIAGNOSES → RECALLS PAST INCIDENT → CREATES ISSUE/PR → REBUILD GOES GREEN**

</div>

## 🏗️ System Architecture

```
   ┌──────────────────────────────────────────────────────────┐
   │        FRONTEND — React + Vite + Tailwind  (:3000)        │
   │  AI Assistant · Incidents · Blast · Provenance · CoChange │
   └──────────────────────────┬───────────────────────────────┘
                              │  Server-Sent Events (live token + step stream)
   ┌──────────────────────────▼───────────────────────────────┐
   │            BACKEND — FastAPI · Python 3.11  (:8000)       │
   │  ┌────────────── LangGraph Agent (StateGraph) ─────────┐  │
   │  │ search_memory → call_claude ⇄ execute_tools         │  │
   │  │                  → synthesize → memory_writer        │  │
   │  └──────────────────────────────────────────────────────┘ │
   └──┬─────────┬─────────┬──────────┬──────────┬──────────────┘
   ┌──▼──┐  ┌───▼───┐ ┌───▼──┐  ┌────▼────┐ ┌───▼─────┐
   │GitHub│  │Jenkins│ │ n8n  │  │ChromaDB │ │  Neo4j  │
   │ API  │  │ :8088 │ │:5678 │  │(vector) │ │ (graph) │
   └──────┘  └───────┘ └──────┘  └─────────┘ └─────────┘
                          8-container Docker Compose stack
```

---

## ⚙️ Tech Stack

| Layer | Technology |
|---|---|
| **Agent Orchestration** | LangGraph `StateGraph` — tool-use loops, streaming, reducers |
| **LLM / Reasoning** | Claude (`claude-sonnet-4-6`) · AsyncAnthropic · token streaming |
| **Backend** | FastAPI · Python 3.11 · fully async · SSE |
| **Vector Memory** | ChromaDB — semantic incident recall |
| **Graph Memory** | Neo4j — error-pattern & fix relationships |
| **Token Optimization** | **Graphify** — graph-based context compression under the hood, cutting LLM token cost |
| **Frontend** | React · Vite · Tailwind · EventSource |
| **CI/CD & Automation** | Jenkins · n8n · GitHub REST + GraphQL |
| **Infrastructure** | Docker Compose (8 containers) · hot-reload dev mounts |

---

## ✨ Five Capabilities (all built & demoable)

| Feature | What it does |
|---|---|
| 🔎 **AI Root-Cause Analysis** | Ask *"why did the build fail?"* → agent searches memory, pulls logs, diagnoses & **cites the matching past incident** |
| 🧠 **Incident Memory** | Every analysis stored back to ChromaDB + Neo4j — the agent **learns from its own history** |
| 💥 **Blast Radius** | Map a PR → impacted services/tests/configs/pipelines → **AI risk verdict** + recall of related past incidents. Hardened for large PRs: paginated file fetch, retry-with-backoff, full-coverage impact counts |
| 🧬 **Code Provenance** | Trace any file's full history (commits → PRs → issues) via a single GraphQL request |
| 🔗 **Co-Change Coupling** | Mine commit history to surface files that **always change together** (hidden coupling) |

---

## 🚀 Why AEON Wins

- **Innovation** — memory-first DevOps AI with a **dual vector + graph** store. Not another log summarizer.
- **Technical depth** — real LangGraph agent, 8 tools, streaming, 3 graph-analytics services, GraphQL optimization.
- **Cost-efficient** — runs **Graphify** under the hood for graph-based context compression, **reducing LLM token cost** on every query.
- **Resilience** — **mock fallback everywhere**: the full demo runs even with zero API tokens.
- **Safety** — human-in-the-loop: issues auto-create, **PRs always require an explicit approve click.**
- **Real value** — directly attacks repeat-incident cost & tribal-knowledge loss that every org suffers.

---

<div align="center">

### The Winning Moment
> 🔍 *"Searching incident memory…"* → ✅ **"Found strong match: `inc_seed_003` — 94% similarity, 3 weeks ago."**
> 🧠 *"Same `androidx.core` conflict, resolved by forcing `core-ktx:1.15.0`."*  **Confidence: 91%.**

**⧗ AEON — Autonomous Engineering Operations Nexus**
*Because your infrastructure should never make the same mistake twice.*

</div>
