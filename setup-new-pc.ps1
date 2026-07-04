<#
  Aeon - New PC Bootstrap
  =======================
  One-shot setup of the full Aeon demo stack on a fresh Windows machine.

  Usage (PowerShell, from the repo root):
    Set-ExecutionPolicy -Scope Process Bypass -Force
    .\setup-new-pc.ps1                 # core stack (Aeon + Jenkins + n8n + memory)
    .\setup-new-pc.ps1 -WithOdysseus   # also start the Odysseus extended workspace
    .\setup-new-pc.ps1 -SkipPrompts    # non-interactive: no key prompts, no optional stages

  What it automates:
    1. Prerequisite checks (Docker running, git; python/node for optional stages)
    2. aeon/backend/.env creation + API key prompts
    3. docker compose up for the 8-service Aeon stack
    4. Health-wait on every service
    5. Memory seeding (5 demo incidents into ChromaDB + Neo4j)
    6. Jenkins job verification (re-seeds the 5 demo jobs if missing)
    7. Optional: n8n workflow import, GitHub Actions tunnel, Odysseus

  What stays manual (the script tells you when):
    - Creating the n8n account in the browser (first run only)
    - Pasting API keys (Anthropic / GitHub / n8n)
#>

param(
    [switch]$WithOdysseus,
    [switch]$SkipPrompts
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AeonDir = Join-Path $Root "aeon"
$EnvPath = Join-Path $AeonDir "backend\.env"
$EnvExample = Join-Path $AeonDir "backend\.env.example"

# -- helpers ------------------------------------------------------------------

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK]   $msg" -ForegroundColor Green }
function Write-Skip($msg)  { Write-Host "    [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn2($msg) { Write-Host "    [!]    $msg" -ForegroundColor Yellow }

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# Run a native command through cmd.exe so stderr never trips $ErrorActionPreference
function Invoke-Native($commandLine) {
    cmd /c $commandLine | Out-Host
    return $LASTEXITCODE
}

function Get-EnvKey($path, $key) {
    $line = Get-Content $path | Where-Object { $_ -match "^\s*$key=" } | Select-Object -First 1
    if ($line) { return $line.Substring($line.IndexOf('=') + 1).Trim() }
    return ""
}

function Set-EnvKey($path, $key, $value) {
    $lines = @(Get-Content $path)
    $found = $false
    $lines = $lines | ForEach-Object {
        if ($_ -match "^\s*$key=") { $found = $true; "$key=$value" } else { $_ }
    }
    if (-not $found) { $lines += "$key=$value" }
    Set-Content -Path $path -Value $lines -Encoding Ascii
}

function Wait-ForUrl($url, $label, $timeoutSec) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -ge 200) { Write-Ok "$label is up"; return $true }
        } catch {
            # 401/403 still means the service is alive (Jenkins, n8n auth pages)
            $status = 0
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -eq 401 -or $status -eq 403) { Write-Ok "$label is up (auth required)"; return $true }
            Start-Sleep -Seconds 3
        }
    }
    Write-Warn2 "$label did not respond within ${timeoutSec}s ($url)"
    return $false
}

# -- 1. Prerequisites --------------------------------------------------------

Write-Step "Checking prerequisites"

if (-not (Test-Cmd "git")) {
    throw "git is not installed. Install from https://git-scm.com and re-run."
}
Write-Ok "git found"

if (-not (Test-Cmd "docker")) {
    throw "Docker Desktop is not installed. Install from https://www.docker.com/products/docker-desktop, start it, then re-run."
}
$code = Invoke-Native "docker info >nul 2>nul"
if ($code -ne 0) {
    throw "Docker Desktop is installed but the engine is not running. Start Docker Desktop, wait for 'Engine running', then re-run."
}
Write-Ok "Docker engine running"

$HasPython = Test-Cmd "python"
if ($HasPython) { Write-Ok "python found (integration scripts available)" }
else { Write-Warn2 "python not found - Jenkins re-seed / n8n import / GitHub Actions stages will be skipped. Install Python 3.10+ to enable them." }

if (-not (Test-Path (Join-Path $AeonDir "docker-compose.yml"))) {
    throw "aeon/docker-compose.yml not found. Run this script from the Project-Aeon repo root."
}

# -- 2. Backend .env ---------------------------------------------------------

Write-Step "Configuring aeon/backend/.env"

if (-not (Test-Path $EnvPath)) {
    Copy-Item $EnvExample $EnvPath
    Write-Ok "Created .env from .env.example"
} else {
    Write-Ok ".env already exists - keeping it"
}

# Jenkins credentials are fixed by the demo image
if (-not (Get-EnvKey $EnvPath "JENKINS_TOKEN")) { Set-EnvKey $EnvPath "JENKINS_TOKEN" "admin" }

if (-not $SkipPrompts) {
    if (-not (Get-EnvKey $EnvPath "ANTHROPIC_API_KEY")) {
        $v = Read-Host "Paste ANTHROPIC_API_KEY (sk-ant-...) - Enter to skip (AI features fall back to mock)"
        if ($v) { Set-EnvKey $EnvPath "ANTHROPIC_API_KEY" $v.Trim(); Write-Ok "ANTHROPIC_API_KEY saved" }
        else { Write-Warn2 "No Anthropic key - risk assessments, narratives and insights will show fallback text" }
    } else { Write-Ok "ANTHROPIC_API_KEY already set" }

    if (-not (Get-EnvKey $EnvPath "GITHUB_TOKEN")) {
        $v = Read-Host "Paste GITHUB_TOKEN (ghp_..., scopes: repo, workflow) - Enter to skip (60 req/hr limit)"
        if ($v) { Set-EnvKey $EnvPath "GITHUB_TOKEN" $v.Trim(); Write-Ok "GITHUB_TOKEN saved" }
        else { Write-Warn2 "No GitHub token - Provenance/Blast/Co-Change will hit the 60 req/hr unauthenticated limit" }
    } else { Write-Ok "GITHUB_TOKEN already set" }
}

# -- 3. Start the Aeon stack -------------------------------------------------

Write-Step "Starting the Aeon stack (8 containers - first build takes 5-10 min)"

Push-Location $AeonDir
try {
    $code = Invoke-Native "docker compose up -d --build"
    if ($code -ne 0) { throw "docker compose up failed (exit $code). Check the output above." }
} finally {
    Pop-Location
}
Write-Ok "Containers started"

# -- 4. Wait for services ---------------------------------------------------

Write-Step "Waiting for services to come up (Jenkins and Neo4j are the slowest)"

$backendUp = Wait-ForUrl "http://localhost:8000/health" "Backend (8000)"  240
$null      = Wait-ForUrl "http://localhost:3000"        "Frontend (3000)" 120
$jenkinsUp = Wait-ForUrl "http://localhost:8088/login"  "Jenkins (8088)"  300
$null      = Wait-ForUrl "http://localhost:5678"        "n8n (5678)"      120
$null      = Wait-ForUrl "http://localhost:7474"        "Neo4j (7474)"    180

if (-not $backendUp) { throw "Backend never became healthy - run 'docker compose logs backend' inside aeon/ and check for errors." }

# -- 5. Seed demo memory -----------------------------------------------------

Write-Step "Seeding incident memory (ChromaDB + Neo4j)"

$seeded = $false
foreach ($attempt in 1..5) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/memory/seed" -Method Post -TimeoutSec 30
        Write-Ok "Seeded $($resp.seeded) incidents (chroma=$($resp.chromadb_stored), neo4j=$($resp.neo4j_stored))"
        $seeded = $true
        break
    } catch {
        Write-Warn2 "Seed attempt $attempt failed - retrying in 10s (memory stores may still be booting)"
        Start-Sleep -Seconds 10
    }
}
if (-not $seeded) { Write-Warn2 "Could not seed memory. Re-run later: Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post" }

# On a first boot with fresh volumes, Neo4j's bolt port often comes up after
# the backend has already connected (and given up). The backend's Neo4j client
# is a startup singleton, so a restart is needed to pick the connection up.
if ($seeded -and $resp.neo4j_stored -eq 0) {
    Write-Warn2 "Neo4j was not ready when the backend started - restarting backend and re-seeding"
    Push-Location $AeonDir
    try { $null = Invoke-Native "docker compose restart backend" } finally { Pop-Location }
    $null = Wait-ForUrl "http://localhost:8000/health" "Backend (after restart)" 120
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/memory/seed" -Method Post -TimeoutSec 30
        Write-Ok "Re-seeded (chroma=$($resp.chromadb_stored), neo4j=$($resp.neo4j_stored))"
    } catch {
        Write-Warn2 "Re-seed failed - run manually: Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post"
    }
}

# -- 6. Verify Jenkins demo jobs ---------------------------------------------

Write-Step "Verifying Jenkins demo jobs"

if ($jenkinsUp) {
    try {
        $auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:admin"))
        $jenkins = Invoke-RestMethod -Uri "http://localhost:8088/api/json?tree=jobs[name]" -Headers @{ Authorization = "Basic $auth" } -TimeoutSec 15
        $jobCount = @($jenkins.jobs).Count
        if ($jobCount -ge 5) {
            Write-Ok "$jobCount demo jobs present"
        } elseif ($HasPython) {
            Write-Warn2 "Only $jobCount jobs found - re-seeding via jenkins-setup/create_jobs.py"
            $null = Invoke-Native "python -m pip install --quiet requests"
            $code = Invoke-Native "python `"$Root\jenkins-setup\create_jobs.py`""
            if ($code -eq 0) { Write-Ok "Jenkins jobs re-seeded" } else { Write-Warn2 "Re-seed failed - run manually: python jenkins-setup/create_jobs.py" }
        } else {
            Write-Warn2 "Only $jobCount jobs found and python is missing - install Python then run: python jenkins-setup/create_jobs.py"
        }
    } catch {
        Write-Warn2 "Could not query Jenkins API yet - jobs auto-seed on first boot; check http://localhost:8088 (admin/admin) in a minute"
    }
}

# -- 7. Optional: n8n workflows ----------------------------------------------

Write-Step "n8n workflow automation (manual account step required)"

if ($SkipPrompts) {
    Write-Skip "Prompts disabled - see SETUP_GUIDE.md section 8 for n8n setup"
} else {
    Write-Host @"

    n8n needs a one-time local account (browser only, no email verification):
      1. A browser tab will open at http://localhost:5678 - sign up with any email/password
      2. Click your avatar (bottom-left) -> Settings -> API -> Create an API key
      3. Paste the key below
"@
    Start-Process "http://localhost:5678"
    $n8nKey = Read-Host "Paste n8n API key - Enter to skip (do later per SETUP_GUIDE.md section 8)"
    if ($n8nKey) {
        Set-EnvKey $EnvPath "N8N_API_KEY" $n8nKey.Trim()
        if ($HasPython) {
            $null = Invoke-Native "python -m pip install --quiet requests"
            $code = Invoke-Native "python `"$Root\n8n-setup\import_workflows.py`" --api-key $($n8nKey.Trim())"
            if ($code -eq 0) { Write-Ok "n8n workflows imported and activated" }
            else { Write-Warn2 "Import failed - run manually: python n8n-setup/import_workflows.py --api-key <key>" }
        } else {
            Write-Warn2 "python missing - run later: python n8n-setup/import_workflows.py --api-key <key>"
        }
        Push-Location $AeonDir
        $null = Invoke-Native "docker compose restart backend"
        Pop-Location
        Write-Ok "Backend restarted with N8N_API_KEY"
    } else {
        Write-Skip "n8n workflows - import later, everything else still works"
    }
}

# -- 8. Optional: GitHub Actions live pipelines ------------------------------

Write-Step "GitHub Actions integration (optional - live workflow runs in Aeon)"

$ghToken = Get-EnvKey $EnvPath "GITHUB_TOKEN"
if ($SkipPrompts -or -not $ghToken -or -not $HasPython) {
    Write-Skip "Needs interactive mode + GITHUB_TOKEN + python. See SETUP_GUIDE.md section 7."
} else {
    $ans = Read-Host "Set up GitHub Actions demo repo + tunnel now? Opens a second window that must stay open during the demo (y/N)"
    if ($ans -eq "y") {
        $null = Invoke-Native "python -m pip install --quiet requests PyNaCl"
        $ghCmd = "cd /d `"$Root\github-actions-setup`" && python setup.py --token $ghToken --repo aeon-demo"
        Start-Process cmd -ArgumentList "/k", $ghCmd
        Write-Ok "Launched in a new window - keep it open; runs appear in Aeon -> Pipelines in 2-3 min"
    } else {
        Write-Skip "GitHub Actions - run later: python github-actions-setup/setup.py --token <ghp_...> --repo aeon-demo"
    }
}

# -- 9. Optional: Odysseus extended workspace --------------------------------

if ($WithOdysseus) {
    Write-Step "Starting Odysseus extended workspace"

    if (-not (Test-Cmd "ollama")) {
        Write-Warn2 "Ollama not installed - install from https://ollama.com, then re-run with -WithOdysseus"
    } else {
        if ($env:OLLAMA_HOST -ne "0.0.0.0") {
            setx OLLAMA_HOST "0.0.0.0" | Out-Null
            $env:OLLAMA_HOST = "0.0.0.0"   # current session too, so ollama serve below inherits it
        }
        # Start Ollama if it isn't already listening. If it IS running but was
        # started without OLLAMA_HOST=0.0.0.0, Docker can't reach it - restart it.
        $ollamaUp = $false
        try {
            $null = Invoke-RestMethod "http://localhost:11434/api/version" -TimeoutSec 3
            $ollamaUp = $true
        } catch { }
        if (-not $ollamaUp) {
            Start-Process -FilePath (Get-Command ollama).Source -ArgumentList "serve" -WindowStyle Hidden
            Write-Ok "Started ollama serve (OLLAMA_HOST=0.0.0.0)"
            Start-Sleep -Seconds 8
        } else {
            Write-Warn2 "Ollama already running. If Odysseus can't reach it, quit Ollama (tray icon) and re-run this script so it restarts with OLLAMA_HOST=0.0.0.0."
        }
        $odyEnv = Join-Path $Root "odysseus-setup\.env"
        if (-not (Test-Path $odyEnv)) {
            # AUTH_ENABLED=false is required: Aeon's backend calls arrive from the
            # Docker bridge network, so the loopback-only LOCALHOST_BYPASS can't
            # authenticate them. Local demo only - don't expose port 7000 to a LAN.
            $odyContent = @(
                "AUTH_ENABLED=false",
                "LOCALHOST_BYPASS=true",
                "OLLAMA_BASE_URL=http://host.docker.internal:11434/v1",
                "ODYSSEUS_ADMIN_PASSWORD=aeon_demo",
                "ALLOWED_ORIGINS=http://localhost:3000,http://localhost:7000,http://localhost:8000,http://127.0.0.1:3000",
                "APP_BIND=0.0.0.0",
                "APP_PORT=7000"
            )
            Set-Content -Path $odyEnv -Value $odyContent -Encoding Ascii
            Write-Ok "Created odysseus-setup/.env"
        }
        Push-Location (Join-Path $Root "odysseus-setup")
        try {
            $code = Invoke-Native "docker compose up -d"
            if ($code -eq 0) { Write-Ok "Odysseus starting (first build takes 5-10 min)" }
            else { Write-Warn2 "Odysseus compose failed (exit $code)" }
        } finally { Pop-Location }
        $odyUp = Wait-ForUrl "http://localhost:7000" "Odysseus (7000)" 600

        # Register the local Ollama server as a model endpoint (idempotent -
        # Odysseus dedupes by base_url). Without this, research/chat return
        # "No endpoints configured".
        if ($odyUp) {
            try {
                $ep = Invoke-RestMethod -Uri "http://localhost:7000/api/model-endpoints" -Method Post -TimeoutSec 30 -Body @{
                    name     = "ollama-local"
                    base_url = "http://host.docker.internal:11434/v1"
                }
                Write-Ok "Ollama endpoint registered in Odysseus (models: $($ep.models -join ', '))"
            } catch {
                Write-Warn2 "Could not auto-register the Ollama endpoint - add it in Odysseus Settings (base URL: http://host.docker.internal:11434/v1)"
            }
        }
        Write-Host @"

    Odysseus notes:
      - Auth is disabled for the Aeon integration - no login needed. Local demo only.
      - Pull a model if you have none:  ollama pull llama3.2
      - Aeon's ODYSSEUS_URL is already set in .env (host.docker.internal:7000)
"@
    }
} else {
    Write-Step "Odysseus extended workspace"
    Write-Skip "Not requested - re-run with -WithOdysseus to add it (needs Ollama)"
}

# -- 10. Final verification --------------------------------------------------

Write-Step "Final verification"

$checks = @(
    @{ Label = "Frontend";        Url = "http://localhost:3000" },
    @{ Label = "Backend health";  Url = "http://localhost:8000/health" },
    @{ Label = "API docs";        Url = "http://localhost:8000/docs" },
    @{ Label = "Jenkins";         Url = "http://localhost:8088/login" },
    @{ Label = "n8n";             Url = "http://localhost:5678" },
    @{ Label = "Neo4j browser";   Url = "http://localhost:7474" }
)
foreach ($c in $checks) {
    try {
        $null = Invoke-WebRequest -Uri $c.Url -UseBasicParsing -TimeoutSec 8
        Write-Ok $c.Label
    } catch { Write-Warn2 "$($c.Label) - not responding ($($c.Url))" }
}

try {
    $mem = Invoke-RestMethod -Uri "http://localhost:8000/api/memory/status" -TimeoutSec 10
    Write-Ok "Memory: chroma=$($mem.chromadb.incident_count) incidents, neo4j connected=$($mem.neo4j.connected)"
} catch { Write-Warn2 "Memory status unavailable" }

Write-Host @"

============================================================
  Aeon is up.

  Open:      http://localhost:3000
  Jenkins:   http://localhost:8088   (admin / admin)
  n8n:       http://localhost:5678   (your local account)
  Neo4j:     http://localhost:7474   (neo4j / aeon_neo4j)
  API docs:  http://localhost:8000/docs

  Demo flow: AI Assistant -> "Why did the Android Gradle build fail?"
             Blast Radius -> expressjs/express PR 7233
             Provenance   -> expressjs/express lib/application.js
             Co-Change    -> expressjs/express, 100 commits

  Details & troubleshooting: SETUP_GUIDE.md
============================================================
"@
