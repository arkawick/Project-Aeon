# Project Aeon — Claude Code Context

AI-powered DevOps operations workspace (hackathon project). Combines GitHub, Jenkins, and n8n with a persistent memory layer (ChromaDB + Neo4j) and a LangGraph agent for CI/CD root-cause analysis. **The differentiator is incident memory** — "this matches incident #421 from 3 weeks ago" — not log summarization. Prioritize the demo scenario over feature completeness: broken build → AI diagnoses → creates issue/PR → rebuild goes green.

## Stack & ports

- Backend: FastAPI, Python 3.11 in Docker (`aeon/backend/`), Claude API via AsyncAnthropic + streaming
- Agent: LangGraph StateGraph — search_memory → call_claude → execute_tools (loop) → synthesize → memory_writer
- Frontend: React + Vite + Tailwind (`aeon/frontend/`)
- Ports: backend 8000, frontend 3000, Jenkins **8088** (not 8080), n8n 5678, ChromaDB 8001, Neo4j 7474/7687, Odysseus 7000

## Running it

```powershell
cd aeon; docker compose up -d                                  # main stack (8 containers)
Invoke-RestMethod http://localhost:8000/api/memory/seed -Method Post   # seed 5 demo incidents
.\setup-new-pc.ps1 -WithOdysseus                               # full bootstrap from nothing (see SETUP_NEW_PC.md)
```

Backend and frontend mount source with hot reload — **backend picks up .py edits automatically** (uvicorn --reload), no rebuild needed. Frontend likewise (Vite dev server).

## Key files

- `aeon/backend/core/instances.py` — shared service singletons (never instantiate services per-request)
- `aeon/backend/agents/graph.py` — LangGraph agent
- `aeon/backend/memory/{chroma_store,neo4j_store}.py` — memory layer (both no-op gracefully when down)
- `aeon/backend/services/{blast_radius,provenance,cochange}_service.py` — the three graph features (SSE streaming)
- `setup-new-pc.ps1` + `SETUP_NEW_PC.md` — tested one-shot machine bootstrap
- Feature docs: `aeon/BLAST_RADIUS.md`, `aeon/CODE_PROVENANCE.md`, `aeon/COCHANGE.md`, `SETUP_GUIDE.md`

## Architecture rules

- Mock fallback everywhere: every integration must keep working (demo-quality) without its token/service
- Human-in-the-loop: issues auto-create; PRs always require an explicit approve click
- Every AI analysis is written back to memory (memory_writer) — the agent improves over time
- New backend features follow the SSE pattern: async generator yielding `{type: step|result|error}` events, router wraps in StreamingResponse

## Hard-won gotchas (each cost real debugging time)

- **`docker compose restart backend` does NOT re-read env_file.** After editing `aeon/backend/.env`, use `docker compose up -d backend`.
- **Neo4j cold-start race:** on first boot with fresh volumes, Neo4j's bolt port comes up after the backend connected and gave up (Neo4jStore is a startup singleton). Symptom: seed reports `neo4j_stored: 0`. Fix: restart backend, re-seed. `setup-new-pc.ps1` self-heals this.
- **Jenkins jobs call `httpRequest`** in post-conditions (webhook to Aeon) — the `http_request` plugin must stay in `aeon/jenkins/plugins.txt` or deploy-staging goes red and no webhooks fire.
- **Odysseus auth:** Aeon's backend reaches Odysseus from the Docker bridge network, never loopback — `LOCALHOST_BYPASS` does NOT apply. `AUTH_ENABLED=false` in `odysseus-setup/.env` is required (local demo only). Odysseus also needs its model endpoint *registered* (discovery isn't enough): `POST http://localhost:7000/api/model-endpoints` form `base_url=http://host.docker.internal:11434/v1` (idempotent).
- **Ollama:** must run with `OLLAMA_HOST=0.0.0.0` or Docker containers can't reach it via `host.docker.internal:11434`.
- **n8n:** account/API key live in the Docker volume — a `down -v` wipes them (browser re-signup required, can't be scripted). Import workflows with `PYTHONUTF8=1 python n8n-setup/import_workflows.py --api-key <key>` (names contain `→`, which crashes cp1252 consoles). Slack/Jira-node workflows can't activate without credentials — expected.
- **Don't test live-vs-mock by substring-matching serialized JSON** (real n8n workflows contain "onError"; check dict keys). Bit us once in `api/n8n.py`.
- **PowerShell scripts must be ASCII.** BOM-less UTF-8 is parsed as ANSI by PS 5.1; an em-dash decodes to a sequence ending in a smart quote, which *terminates strings*. No `&&` / ternary in PS 5.1 either.
- **GitHub API without `GITHUB_TOKEN`** = 60 req/hr — kills Provenance/Blast/Co-Change after ~2 runs. Provenance uses a single GraphQL request when a token exists; REST fallback otherwise.
- `.env` files are gitignored (`aeon/backend/.env`, `odysseus-setup/.env`) — keys never travel with the repo.

## Demo cheat sheet

| Page | Input |
|---|---|
| AI Assistant `/ai` | "Why did the Android Gradle build fail?" → memory match ~60% on inc_seed_004 |
| Blast Radius `/blast` | `expressjs/express` PR `7233` |
| Provenance `/provenance` | `expressjs/express` + `lib/application.js` (~2s with token) |
| Co-Change `/cochange` | `expressjs/express`, 100 commits (finds ci.yml ↔ legacy.yml at 100%) |

**Guaranteed memory-recall moment:** Blast Radius recall on PR 7233 needs incident `inc_demo_421` (content-disposition / response.js / package.json) in ChromaDB — fires at ~78%. Re-store it after any volume wipe (see memory seed pattern in `aeon/backend/api/memory.py`).

Quick smoke test after any change:

```bash
curl -s http://localhost:8000/api/integrations/status   # all "live" except Claude API without key
curl -sN "http://localhost:8000/api/blast/stream?repo=expressjs/express&pr=7233" | grep -c '"type": "result"'
```

## Known gaps

- `ANTHROPIC_API_KEY` unset → all AI surfaces (risk assessment, narratives, coupling insight, live analysis) return mock/fallback text. Model id `claude-sonnet-4-6` is hardcoded in three services.
- No automated tests; verification is the smoke-curl pattern above.
