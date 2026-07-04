# Moving the Aeon Demo to a New PC

The complete flow, start to finish. The heavy lifting is automated by `setup-new-pc.ps1`; this doc covers what to do before, how to run it, and the few steps that must stay manual.

> For deep detail on any individual service, see [SETUP_GUIDE.md](SETUP_GUIDE.md).

---

## Part 0 — On the OLD PC (do this first!)

`.env` files are **gitignored** — your API keys and Odysseus config do NOT travel with the repo.

1. **Commit and push everything:**
   ```powershell
   git add -A
   git commit -m "Pre-migration checkpoint"
   git push origin main
   ```
2. **Copy your secrets somewhere safe** (password manager / notes app):
   - `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` from `aeon/backend/.env`
   - (Or plan to generate fresh ones — links in Part 2)

That's it. Docker volumes (Jenkins jobs, seeded memory) do not need to be copied — the setup script recreates all demo data on the new machine.

---

## Part 1 — On the NEW PC: install prerequisites

| Tool | Required? | Notes |
|---|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop) | **Yes** | Enable WSL 2 backend when the installer asks. **Start it and wait for "Engine running"** before Part 2 |
| [Git](https://git-scm.com) | **Yes** | Defaults are fine |
| [Python 3.10+](https://www.python.org/downloads) | Recommended | Needed only for the integration helper scripts (Jenkins re-seed, n8n import, GitHub Actions). Tick **"Add python.exe to PATH"** |
| [Node.js 18+](https://nodejs.org) | Optional | Only needed for the GitHub Actions tunnel (`localtunnel`) |
| [Ollama](https://ollama.com) | Optional | Only if you want the Odysseus extended workspace |

---

## Part 2 — Clone and run the bootstrap script

```powershell
git clone https://github.com/arkawick/Project-Aeon.git
cd Project-Aeon

Set-ExecutionPolicy -Scope Process Bypass -Force
.\setup-new-pc.ps1
```

Add `-WithOdysseus` if you want the extended workspace too (requires Ollama installed):

```powershell
.\setup-new-pc.ps1 -WithOdysseus
```

The script will:

1. Verify Docker is running (fails fast with a clear message if not)
2. Create `aeon/backend/.env` and **prompt you to paste** `ANTHROPIC_API_KEY` and `GITHUB_TOKEN`
   - Anthropic key: https://console.anthropic.com → API Keys
   - GitHub token: GitHub → Settings → Developer settings → Personal access tokens (classic) → scopes `repo` + `workflow`
   - Both are skippable — Aeon falls back to mock mode — but **set both for the real demo**
3. Build and start all 8 containers (first build: **5–10 minutes**)
4. Wait for every service to come up and seed the 5 demo incidents into memory
5. Verify Jenkins has its 5 demo jobs (re-seeds them if missing)
6. Walk you through the two manual steps below
7. Print a final health check + demo cheat sheet

---

## Part 3 — The manual steps (script pauses for these)

### n8n account (2 minutes, once)
n8n requires a browser signup — it cannot be scripted:
1. The script opens http://localhost:5678 — sign up with any email/password (local only)
2. Avatar (bottom-left) → **Settings** → **API** → **Create an API key**
3. Paste the key back into the script prompt — it imports both workflows and restarts the backend

### GitHub Actions live pipelines (optional)
If you say yes at the prompt, the script opens a **second window** running the tunnel + repo setup. That window must **stay open during the demo** — GitHub can only reach your machine through the tunnel.

### Odysseus (only with `-WithOdysseus`)
1. If the script set `OLLAMA_HOST`, **quit and restart Ollama** (tray icon) so it listens on `0.0.0.0`
2. `ollama pull llama3.2` if you have no models
3. That's it — the script disables Odysseus auth (required so Aeon's Docker backend can call its API; local demo only) and auto-registers your Ollama server as a model endpoint. No login or account needed.

---

## Part 4 — Demo-day checklist (every boot)

```powershell
# 1. Start Docker Desktop, wait for "Engine running", then:
cd Project-Aeon\aeon
docker compose up -d

# 2. (only if using Odysseus) — from repo root:
cd ..\odysseus-setup; docker compose up -d

# 3. Quick smoke check:
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/memory/status
```

| Page | URL | Demo input |
|---|---|---|
| Dashboard | http://localhost:3000 | — |
| AI Assistant | /ai | *"Why did the Android Gradle build fail?"* |
| Blast Radius | /blast | `expressjs/express` PR `7233` |
| Code Provenance | /provenance | `expressjs/express` + `lib/application.js` |
| Co-Change | /cochange | `expressjs/express`, 100 commits |
| Jenkins | http://localhost:8088 | admin / admin |
| n8n | http://localhost:5678 | your local account |

**Tip — guarantee the memory-recall moment:** seed an incident that mentions the files of the PR you'll analyze (e.g. one referencing `response.js` / `package.json` before demoing express PR 7233), so Blast Radius shows *"matches incident … "* deterministically.

---

## If something breaks

| Symptom | Fix |
|---|---|
| Script says Docker not running | Start Docker Desktop, wait for the whale icon to settle, re-run the script (it's safe to re-run) |
| A service shows `[!]` in the final check | `cd aeon; docker compose logs <service> --tail 50` |
| AI answers look canned | `ANTHROPIC_API_KEY` missing → add to `aeon/backend/.env`, then `docker compose up -d backend` |
| Provenance/Blast rate-limited | `GITHUB_TOKEN` missing → same fix as above |
| Full reset | `cd aeon; docker compose down -v; cd ..; .\setup-new-pc.ps1` |

More: [SETUP_GUIDE.md → Troubleshooting](SETUP_GUIDE.md#12-troubleshooting)
