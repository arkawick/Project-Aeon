# Running Project Aeon

## Quick Start (Docker — the only supported way)

```powershell
cd aeon
docker compose up -d
```

All 8 services start together. Wait ~30 seconds for Neo4j and ChromaDB to initialize, then open http://localhost:3000.

### Seed memory (run once after first start)

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Loads 5 demo incidents into ChromaDB and Neo4j so the AI has history to match against.

---

## Stop everything

```powershell
cd aeon
docker compose down
```

Wipe all stored data too (volumes):
```powershell
docker compose down -v
```

---

## Check status

```powershell
docker compose ps
```

All containers should show `Up`:

```
NAME                STATUS          PORTS
aeon-backend-1      Up              0.0.0.0:8000->8000/tcp
aeon-frontend-1     Up              0.0.0.0:3000->3000/tcp
aeon-jenkins-1      Up (healthy)    0.0.0.0:8088->8080/tcp
aeon-n8n-1          Up (healthy)    0.0.0.0:5678->5678/tcp
aeon-neo4j-1        Up              0.0.0.0:7474->7474/tcp
aeon-chromadb-1     Up              0.0.0.0:8001->8000/tcp
aeon-postgres-1     Up              0.0.0.0:5432->5432/tcp
aeon-redis-1        Up              0.0.0.0:6379->6379/tcp
```

> **Note:** Jenkins is mapped to host port **8088** (not 8080). Port 8080 is blocked by a WSL/Tomcat process on this machine.

---

## View logs

All services:
```powershell
docker compose logs -f
```

Single service:
```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f jenkins
```

---

## Restart a single service

```powershell
docker compose restart backend
```

> **Important:** `restart` does NOT apply new environment variables from `docker-compose.yml`. To apply env var changes, use:
> ```powershell
> docker compose up -d --force-recreate backend
> ```

---

## Rebuild after dependency changes

Code changes hot-reload automatically (volumes mount the source). Only rebuild if you change `requirements.txt` or `package.json`:

```powershell
docker compose up -d --build backend
docker compose up -d --build frontend
```

---

## Environment variables

All config lives in `aeon/backend/.env`. Copy from the example:

```powershell
copy aeon\backend\.env.example aeon\backend\.env
```

Key variable for live AI responses:
```
ANTHROPIC_API_KEY=sk-ant-...
```

Without it, the backend falls back to mock streaming — the full demo still works.

After editing `.env`, force-recreate the backend to apply changes:
```powershell
docker compose up -d --force-recreate backend
```

---

## Running locally without Docker (dev mode)

Only the databases need Docker. Backend and frontend can run on the host:

```powershell
# Start databases only
cd aeon
docker compose up -d chromadb neo4j postgres redis

# Backend
cd aeon/backend
pip install -r requirements.txt
copy .env.example .env       # then add ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd aeon/frontend
npm install
npm run dev
# → http://localhost:5173
```

> In local dev mode the frontend runs on **5173** (Vite default), not 3000. The Vite proxy automatically points to `localhost:8000`.

---

## Known issues

| Issue | Cause | Fix |
|---|---|---|
| Pipelines page empty | Vite proxy broken in Docker | `docker compose up -d --force-recreate frontend` |
| Jenkins not loading at 8080 | WSL/Tomcat owns port 8080 | Use **http://localhost:8088** instead |
| Graph page empty after restart | Neo4j still initializing | Wait 30s, click Refresh |
| AI returns no results | `ANTHROPIC_API_KEY` not set | Add to `.env`, force-recreate backend |
