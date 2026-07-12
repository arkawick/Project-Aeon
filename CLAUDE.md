# Project Aeon — Claude Code Context

AI-powered DevOps operations workspace (hackathon project). Combines GitHub, Jenkins, and n8n with a persistent memory layer (ChromaDB + Neo4j) and a LangGraph agent for CI/CD root-cause analysis. **The differentiator is incident memory** — "this matches incident #421 from 3 weeks ago" — not log summarization. Prioritize the demo scenario over feature completeness: broken build → AI diagnoses → creates issue/PR → rebuild goes green.

## Stack & ports

- Backend: FastAPI, Python 3.11 in Docker (`aeon/backend/`)
- **LLM: provider-agnostic (`core/llm.py`)** — Azure OpenAI (`gpt-5-mini`) **or** Claude (`claude-sonnet-4-6`), auto-detected (Azure wins if both keys set; `LLM_PROVIDER` forces). `run_turn()` does real tool-calling on both (Anthropic ⇄ OpenAI translation); `complete()` for single-shot surfaces. Mock without any key.
- Agent: LangGraph StateGraph — search_memory → call_claude → execute_tools (loop) → synthesize → memory_writer. `search_memory` auto-fetches the failing Jenkins log + runs two-stage retrieval (`services/rerank.py`) + GraphRAG expansion (`services/graphrag.py`); `call_claude` uses `llm.run_turn` so the loop runs on either provider.
- Frontend: React + Vite + Tailwind (`aeon/frontend/`)
- Ports: backend 8000, frontend 3000, Jenkins **8088** (not 8080), n8n 5678, ChromaDB 8001, Neo4j 7474/7687, Odysseus 7000

## Running it

```powershell
cd aeon; docker compose up -d                                  # main stack (8 containers)
Invoke-RestMethod http://localhost:8000/api/memory/seed -Method Post   # seed 6 demo incidents (incl. inc_demo_421)
.\reseed.ps1                                                   # same seed, from repo root (idempotent) — run before a demo
.\setup-new-pc.ps1 -WithOdysseus                               # full bootstrap from nothing (see SETUP_NEW_PC.md)
```

Backend and frontend mount source with hot reload — **backend picks up .py edits automatically** (uvicorn --reload), no rebuild needed. Frontend likewise (Vite dev server). **Adding a pip dependency needs a rebuild** (`docker compose build backend`) — reload only re-imports .py.

## Key files

- `aeon/backend/core/instances.py` — shared service singletons (never instantiate services per-request)
- `aeon/backend/core/llm.py` — provider-agnostic LLM layer (Azure/Anthropic/mock; `complete()` + `run_turn()`)
- `aeon/backend/agents/graph.py` — LangGraph agent (provider-agnostic via `run_turn`)
- `aeon/backend/memory/{chroma_store,neo4j_store}.py` — memory layer (both no-op gracefully when down; Neo4j self-heals — see gotcha)
- `aeon/backend/services/rerank.py` + `graphrag.py` — two-stage retrieval re-rank + GraphRAG graph expansion (feed `search_memory`)
- `aeon/backend/services/{blast_radius,provenance,cochange}_service.py` — the three graph features (SSE streaming)
- `reseed.ps1` — restore demo memory (6 incidents) after a `down -v`; `setup-new-pc.ps1` + `SETUP_NEW_PC.md` — tested one-shot machine bootstrap
- Feature docs: `aeon/BLAST_RADIUS.md`, `aeon/CODE_PROVENANCE.md`, `aeon/COCHANGE.md`, `SETUP_GUIDE.md`

## Architecture rules

- Mock fallback everywhere: every integration must keep working (demo-quality) without its token/service
- **Route every LLM call through `core/llm.py`** (never import `anthropic`/`openai` in a service) — that's what keeps the app provider-agnostic
- Two-stage retrieval + GraphRAG: recall goes through `rerank.recall()` (blended score, write-backs excluded); the matched incidents anchor a Neo4j graph expansion injected into the prompt
- Human-in-the-loop: issues auto-create; PRs always require an explicit approve click
- Every AI analysis is written back to memory (memory_writer) — the agent improves over time; **write-backs (`status=analyzed`) are excluded from grounding recall** so the agent never cites its own past output
- New backend features follow the SSE pattern: async generator yielding `{type: step|result|error}` events, router wraps in StreamingResponse

## Hard-won gotchas (each cost real debugging time)

- **`docker compose restart backend` does NOT re-read env_file.** After editing `aeon/backend/.env`, use `docker compose up -d backend`.
- **Neo4j cold-start race — now self-heals.** Bolt used to come up after the backend's startup singleton gave up (symptom: `neo4j_stored: 0`). `Neo4jStore._ensure_driver()` now retries the connection on the next store/read call (throttled to every 5s), so it recovers without a restart. If it still shows 0, check backend logs for `[Neo4jStore] Connection failed`.
- **ChromaDB persistence:** the `chromadb/chroma:latest` (1.x) image persists to **`/data`**, NOT `/chroma/chroma`. The volume must mount at `/data` (fixed in `docker-compose.yml`) or all memory is silently lost on restart. Its healthcheck was removed — the minimal image has no curl/python/wget to probe with (nothing depends on its health; it shows a clean "Up").
- **Azure OpenAI = `gpt-5-mini`, a reasoning model:** use `max_completion_tokens` (not `max_tokens`) with headroom or the visible answer comes back empty (reasoning tokens eat the budget); `core/llm.py` floors it. `AZURE_OPENAI_ENDPOINT` is the **full** chat-completions URL (APIM gateway) — the SDK is pointed at it directly with the `api-key` header. Adding Azure needs `openai` in requirements → **rebuild the image**, reload won't install it.
- **Recall thresholds are on the BLENDED scale** (`services/rerank.py`), not raw cosine — `MEMORY_MATCH_THRESHOLD = 0.45` in `graph.py` gates the blended score (~0.54 for the android match). Don't compare it to a raw cosine number.
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
| AI Assistant `/ai` | "Why did the Android Gradle build fail?" → auto-fetches the real `android-build` failing log, matches `inc_seed_003` (blended ~0.54, "1 month ago"), ~90–95% confidence. Deep Research mode makes it fan out to Jenkins+GitHub+Neo4j+ChromaDB tool calls. |
| Blast Radius `/blast` | `expressjs/express` PR `7233` |
| Provenance `/provenance` | `expressjs/express` + `lib/application.js` (~2s with token) |
| Co-Change `/cochange` | `expressjs/express`, 100 commits (finds ci.yml ↔ legacy.yml at 100%) |

**Guaranteed memory-recall moment:** Blast Radius recall on PR 7233 fires at ~0.78 on `inc_demo_421` (content-disposition / response.js / package.json). **This incident is now folded into the `/api/memory/seed` endpoint** (`api/memory.py` `SEED_INCIDENTS`), so a plain seed / `reseed.ps1` restores it — no manual re-store after a wipe.

Quick smoke test after any change:

```bash
curl -s http://localhost:8000/api/integrations/status   # "AI (LLM)" slot shows provider: azure | anthropic | mock
curl -sN "http://localhost:8000/api/blast/stream?repo=expressjs/express&pr=7233" | grep -c '"type": "result"'
curl -sN "http://localhost:8000/api/ai/stream?query=Why%20did%20the%20android-build%20fail" | grep -c '"type": "result"'
```

## Known gaps

- **No LLM key at all** (neither `AZURE_OPENAI_*` nor `ANTHROPIC_API_KEY`) → all AI surfaces (risk assessment, narratives, coupling insight, live analysis) return mock/fallback text. Model ids are now centralized in `core/llm.py` (`AZURE_OPENAI_DEPLOYMENT` / `CLAUDE_MODEL_ID`), no longer hardcoded per service.
- GitHub Actions `Notify Aeon (failure)` step doesn't attach logs (Jenkins sends up to 4000 chars); a failed build is auto-indexed to ChromaDB (`status=open`) but NOT auto-diagnosed — the agent runs only when a human asks about it.
- No automated tests; verification is the smoke-curl pattern above.
