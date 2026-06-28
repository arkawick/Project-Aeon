@echo off
setlocal enabledelayedexpansion
title Aeon — Demo Setup

echo.
echo  ██████████████████████████████████████████████
echo     AEON — AI Ops Workspace  ^|  Demo Setup
echo  ██████████████████████████████████████████████
echo.

REM ── 1. Start all Docker services ────────────────────────────────────────────
echo [1/6] Starting Docker services...
docker compose up -d --build
if errorlevel 1 (
    echo ERROR: docker compose failed. Is Docker Desktop running?
    pause
    exit /b 1
)
echo       Done.

REM ── 2. Wait for ChromaDB ────────────────────────────────────────────────────
echo [2/6] Waiting for ChromaDB to be ready...
:wait_chroma
timeout /t 3 /nobreak >nul
curl -s -f http://localhost:8001/api/v1/heartbeat >nul 2>&1
if errorlevel 1 goto wait_chroma
echo       ChromaDB ready.

REM ── 3. Wait for backend ─────────────────────────────────────────────────────
echo [3/6] Waiting for Aeon backend...
:wait_backend
timeout /t 3 /nobreak >nul
curl -s -f http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_backend
echo       Backend ready.

REM ── 4. Seed ChromaDB with demo incidents ────────────────────────────────────
echo [4/6] Seeding incident memory...
curl -s -X POST http://localhost:8000/api/memory/seed >nul
echo       Memory seeded.

REM ── 5. Wait for Jenkins ──────────────────────────────────────────────────────
echo [5/6] Waiting for Jenkins (this can take 60-90s on first boot)...
:wait_jenkins
timeout /t 5 /nobreak >nul
curl -s -f http://localhost:8080/login >nul 2>&1
if errorlevel 1 goto wait_jenkins
echo       Jenkins ready.

REM ── 6. Open browser tabs ─────────────────────────────────────────────────────
echo [6/6] Opening Aeon dashboard...
timeout /t 2 /nobreak >nul
start "" "http://localhost:3000"
timeout /t 1 /nobreak >nul
start "" "http://localhost:8080"
timeout /t 1 /nobreak >nul
start "" "http://localhost:5678"

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║  Aeon is running!                                ║
echo  ║                                                  ║
echo  ║  Dashboard    →  http://localhost:3000           ║
echo  ║  Jenkins      →  http://localhost:8080           ║
echo  ║  n8n          →  http://localhost:5678           ║
echo  ║  API docs     →  http://localhost:8000/docs      ║
echo  ║  Neo4j        →  http://localhost:7474           ║
echo  ║                                                  ║
echo  ║  Jenkins login:  admin / admin                   ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  Import n8n workflows:
echo    1. Open http://localhost:5678
echo    2. Menu → Workflows → Import from File
echo    3. Import: aeon\n8n\workflows\notify-slack.json
echo    4. Import: aeon\n8n\workflows\auto-create-issue.json
echo    5. Activate both workflows
echo.
pause
