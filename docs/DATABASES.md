# Inspecting Databases (without a UI)

## PostgreSQL

Connect and list tables:
```powershell
docker exec aeon-postgres-1 psql -U aeon -d aeon -c "\dt"
```

Run any SQL query:
```powershell
docker exec aeon-postgres-1 psql -U aeon -d aeon -c "SELECT * FROM incidents LIMIT 10;"
```

Count rows in a table:
```powershell
docker exec aeon-postgres-1 psql -U aeon -d aeon -c "SELECT COUNT(*) FROM incidents;"
```

Interactive psql shell:
```powershell
docker exec -it aeon-postgres-1 psql -U aeon -d aeon
```
Then type SQL freely. Exit with `\q`.

---

## Redis

Ping (should return PONG):
```powershell
docker exec aeon-redis-1 redis-cli PING
```

List all keys:
```powershell
docker exec aeon-redis-1 redis-cli KEYS "*"
```

Get a value by key:
```powershell
docker exec aeon-redis-1 redis-cli GET "your-key-name"
```

Get key type + TTL:
```powershell
docker exec aeon-redis-1 redis-cli TYPE "your-key-name"
docker exec aeon-redis-1 redis-cli TTL "your-key-name"
```

Count all keys:
```powershell
docker exec aeon-redis-1 redis-cli DBSIZE
```

Interactive redis-cli shell:
```powershell
docker exec -it aeon-redis-1 redis-cli
```

---

## ChromaDB

ChromaDB exposes a REST API on port 8001.

Heartbeat (is it alive?):
```powershell
Invoke-RestMethod -Uri http://localhost:8001/api/v2/heartbeat
```

List collections:
```powershell
Invoke-RestMethod -Uri http://localhost:8001/api/v2/collections
```

Or via the backend API (easier):
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/status
```

Semantic search:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/memory/search?q=gradle+dependency+conflict&top_k=3"
```

---

## Neo4j

Neo4j has a full browser UI at **http://localhost:7474** (credentials: `neo4j / aeon_neo4j`).

You can also query it via the backend API:

Top recurring error types:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/top-errors
```

Full knowledge graph (nodes + edges):
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/graph
```

Or run Cypher directly in the container:
```powershell
docker exec aeon-neo4j-1 cypher-shell -u neo4j -p aeon_neo4j "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC"
```

---

## Seed all memory stores at once

Run this once after starting the stack to populate ChromaDB and Neo4j with 5 demo incidents:

```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Then verify:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/status
```

Expected response:
```json
{
  "chromadb": { "connected": true, "incident_count": 5 },
  "neo4j":    { "connected": true, "top_error_types": [...] }
}
```
