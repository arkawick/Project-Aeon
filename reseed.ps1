# reseed.ps1 - Restore Aeon demo incident memory after a volume wipe (down -v) or a
# fresh boot. Idempotent: safe to run multiple times (the seed endpoint upserts).
#
# Seeds 6 incidents into ChromaDB + Neo4j, including inc_demo_421 which powers the
# Blast Radius memory recall on expressjs/express PR 7233.
#
# Usage:
#   .\reseed.ps1
#   .\reseed.ps1 -BackendUrl http://localhost:8000
#
# NOTE: ASCII-only on purpose - PowerShell 5.1 mis-parses BOM-less UTF-8, and a
# stray em-dash/smart-quote can terminate a string. Keep it plain ASCII.

param(
    [string]$BackendUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Aeon reseed - restoring demo incident memory via $BackendUrl" -ForegroundColor Cyan
Write-Host ""

# 1. Seed both memory stores
try {
    $resp = Invoke-RestMethod -Uri "$BackendUrl/api/memory/seed" -Method Post -TimeoutSec 30
} catch {
    Write-Host "ERROR: could not reach the backend at $BackendUrl." -ForegroundColor Red
    Write-Host "Is the stack up?  cd aeon; docker compose up -d" -ForegroundColor Yellow
    exit 1
}

Write-Host ("Seeded {0} incidents  ->  ChromaDB stored: {1}  |  Neo4j stored: {2}" -f `
    $resp.seeded, $resp.chromadb_stored, $resp.neo4j_stored) -ForegroundColor Green

# 2. Neo4j cold-start race guard (documented gotcha). On a fresh boot the bolt
#    port can come up after the backend's Neo4j singleton already gave up, so the
#    seed reports neo4j_stored = 0. Fix: restart backend, then reseed.
if ($resp.neo4j_stored -eq 0) {
    Write-Host ""
    Write-Host "WARNING: neo4j_stored = 0 (Neo4j cold-start race)." -ForegroundColor Yellow
    Write-Host "Fix: docker compose up -d backend   (wait ~10s)   then re-run .\reseed.ps1" -ForegroundColor Yellow
}

# 3. Confirm the final ChromaDB count
try {
    $status = Invoke-RestMethod -Uri "$BackendUrl/api/memory/status" -Method Get -TimeoutSec 15
    Write-Host ("ChromaDB now holds {0} incident(s)." -f $status.chromadb.incident_count) -ForegroundColor Green
} catch {
    Write-Host "Seed succeeded but status check failed (non-fatal)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Demo memory restored (includes inc_demo_421 for Blast Radius recall on express PR 7233)." -ForegroundColor Cyan
Write-Host ""
