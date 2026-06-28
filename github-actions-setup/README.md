# GitHub Actions — Real Integration Setup

Connects real GitHub Actions runs to Aeon using localtunnel (free, no account needed).

---

## How it works

```
GitHub Actions (cloud) → localtunnel public URL → localhost:8000 (Aeon)
```

Every workflow run (pass or fail) POSTs to Aeon's `/api/pipelines/ingest` endpoint.
Aeon stores the logs in ChromaDB and shows them in the Pipelines page.

---

## Prerequisites

| Requirement | How to get it |
|---|---|
| Node.js | Already installed (used for the frontend) |
| Python `requests` + `PyNaCl` | `pip install requests PyNaCl` |
| GitHub Personal Access Token | See below |

### Get a GitHub PAT

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. **Generate new token (classic)**
3. Scopes: check `repo` and `workflow`
4. Copy the token (`ghp_...`)

---

## One-command setup

Make sure Aeon is running first (`docker compose up -d` in `aeon/`), then:

```powershell
cd github-actions-setup
pip install requests PyNaCl
python setup.py --token ghp_YOUR_TOKEN --repo aeon-demo
```

That's it. The script will:
1. Start a localtunnel → get a public URL for localhost:8000
2. Create the GitHub repo `aeon-demo` under your account
3. Add `AEON_URL` as an encrypted secret in the repo
4. Push all 5 workflow files to `.github/workflows/`
5. Trigger initial runs

---

## Options

```
python setup.py --token TOKEN --repo aeon-demo
    --subdomain aeon-demo       # localtunnel subdomain (tries to be stable)
    --port 8000                 # Aeon backend port
    --tunnel-url https://...    # skip localtunnel, use your own URL
    --skip-trigger              # don't trigger runs automatically
```

Use an org repo:
```powershell
python setup.py --token ghp_xxx --repo my-org/aeon-demo
```

---

## Workflows

| File | What it does | Result |
|---|---|---|
| `frontend-build.yml` | Node 20 + Vite build | Fails (missing path alias) |
| `backend-tests.yml` | Python pytest + postgres | Fails (OOM in integration tests) |
| `android-build.yml` | Gradle + Android SDK | Fails (androidx.core conflict) |
| `docker-image-build.yml` | Docker build | Fails (disk full) |
| `deploy-staging.yml` | Kubernetes staging deploy | Passes |

All workflows notify Aeon on both success and failure.

---

## After setup

Open **http://localhost:3000/pipelines** — GitHub Actions runs appear here within seconds of completing.

Open **http://localhost:3000/ai** and ask:
```
Why did the Android build fail?
```
Aeon will search its memory, find the matching incident, and explain with a fix.

---

## Important: tunnel must stay running

The localtunnel process keeps the terminal open. GitHub Actions can only reach Aeon while the tunnel is active.

If you restart the tunnel, the URL may change. Re-run the setup script to update the `AEON_URL` secret:
```powershell
python setup.py --token ghp_xxx --repo aeon-demo
```

For a permanent URL, use **Cloudflare Tunnel** (free) instead:
```powershell
# Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
cloudflared tunnel --url http://localhost:8000
# Then:
python setup.py --token ghp_xxx --repo aeon-demo --tunnel-url https://your-tunnel.trycloudflare.com
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip install PyNaCl` fails | Install Visual C++ build tools on Windows, then retry |
| localtunnel URL not working | Subdomain taken — try `--subdomain aeon-demo-2` |
| Workflow not triggering | Go to repo → Actions → enable workflows manually (first time) |
| Aeon not receiving events | Check tunnel is running, check `/health` returns OK |
| `403` from GitHub API | PAT missing `repo` or `workflow` scope — regenerate |
