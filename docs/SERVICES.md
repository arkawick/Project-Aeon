# Services & URLs

All services run via `docker compose up -d` from the `aeon/` directory.

## Browser UIs

| Service | URL | Credentials | Notes |
|---|---|---|---|
| **Aeon Frontend** | http://localhost:3000 | — | Main app |
| **Backend API Docs** | http://localhost:8000/docs | — | Swagger UI |
| **Jenkins** | http://localhost:8088 | admin / admin | Port 8088 — 8080 blocked by WSL |
| **n8n** | http://localhost:5678 | — | No auth in dev |
| **Neo4j Browser** | http://localhost:7474 | neo4j / aeon_neo4j | Graph explorer |
| **Odysseus** | http://localhost:7000 | admin / aeon_demo | Extended AI workspace (separate stack) |

## API / TCP endpoints (no browser UI)

| Service | Port | Notes |
|---|---|---|
| **Backend API** | 8000 | FastAPI REST |
| **ChromaDB** | 8001 | REST API at `/api/v2/` |
| **PostgreSQL** | 5432 | DB: `aeon`, User: `aeon`, Pass: `aeon` |
| **Redis** | 6379 | No auth |

---

## Backend API — key endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/memory/status` | ChromaDB + Neo4j connectivity + counts |
| POST | `/api/memory/seed` | Load 5 demo incidents into memory |
| GET | `/api/memory/graph` | Full Neo4j graph for Knowledge Graph page |
| GET | `/api/memory/top-errors` | Most frequent error types |
| GET | `/api/memory/search?q=...` | Semantic search over ChromaDB |
| GET | `/api/pipelines/` | List all pipeline runs (GitHub + Jenkins + ingested) |
| POST | `/api/pipelines/ingest` | Receive CI/CD webhook events |
| GET | `/api/incidents/` | List all incidents |
| POST | `/api/ai/analyze` | Run the LangGraph agent (SSE streaming) |

Full interactive docs at **http://localhost:8000/docs**

---

## Docker networking

The backend and frontend communicate over Docker's internal network using service names:

| From → To | Address used |
|---|---|
| Frontend → Backend (via Vite proxy) | `http://backend:8000` |
| Backend → ChromaDB | `http://chromadb:8000` |
| Backend → Neo4j | `bolt://neo4j:7687` |
| Backend → Jenkins | `http://jenkins:8080` |
| Backend → n8n | `http://n8n:5678` |
| Backend → Postgres | `postgresql://aeon:aeon@postgres:5432/aeon` |
| Backend → Redis | `redis://redis:6379` |
| Backend → Odysseus | `http://host.docker.internal:7000` (separate stack, host network) |

> External access (browser, curl) always uses `localhost` with the mapped host port.

---

## ChromaDB

- **Heartbeat:** http://localhost:8001/api/v2/heartbeat
- **Collections:** http://localhost:8001/api/v2/collections
- **Version:** latest (v2 API — v1 is deprecated)
- **Data volume:** `chroma_data`

## Neo4j

- **Browser UI:** http://localhost:7474
- **Bolt:** `bolt://localhost:7687`
- **Username:** `neo4j` / **Password:** `aeon_neo4j`
- **Plugins:** APOC enabled
- **Data volume:** `neo4j_data`

## Jenkins

- **URL:** http://localhost:8088 (host port 8088 → container port 8080)
- **Username:** `admin` / **Password:** `admin`
- **Setup wizard:** disabled (starts ready)
- **Pre-loaded jobs:** 5 (see `jenkins-setup/README.md`)
- **Data volume:** `jenkins_data`

## n8n

- **URL:** http://localhost:5678
- **Data volume:** `n8n_data`

## PostgreSQL

- **Host:** localhost:5432
- **Database:** `aeon` / **User:** `aeon` / **Password:** `aeon`
- **Data volume:** `postgres_data`

## Redis

- **Host:** localhost:6379
- **No authentication** (dev mode)

## Odysseus (Extended Workspace)

- **URL:** http://localhost:7000
- **Username:** `admin` / **Password:** `aeon_demo`
- **Stack:** separate `docker compose up -d` from `odysseus-setup/`
- **Aeon backend reaches it via:** `http://host.docker.internal:7000` (set in `ODYSSEUS_URL` env var)
- **Bundled services:** SearXNG on port 8082, ChromaDB on port 8100, ntfy on port 8091
