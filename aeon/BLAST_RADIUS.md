# Blast Radius Analyzer

Answers the question: **"If I merge this PR, what breaks?"**

Given any public GitHub pull request, maps every changed file to the services, tests, configs, pipelines, and infrastructure it touches — then asks Claude for a risk assessment and deploy recommendation before you hit merge.

---

## How it works

```
PR number
    │
    ▼
GitHub PR API → changed files list
    │
    ├──► Classify each file (Service / Test / Config / Pipeline / Infrastructure / Dependencies / Docs)
    ├──► Infer service names from directory structure
    ├──► Build impact graph  (PR → Files → Impact areas)
    ├──► Incident memory recall (ChromaDB vector search over past incidents)
    └──► Claude risk assessment (HIGH / MEDIUM / LOW + deploy recommendation)
```

Results stream live to the browser as files are classified. The graph renders in **Radial layout** by default — PR at the center, changed files in the middle ring, impacted areas in the outer ring — so the "blast spreading outward" is immediately visible.

---

## Prerequisites

| Requirement | Why | Where to get it |
|---|---|---|
| `GITHUB_TOKEN` | 5000 req/hr (required for large PRs) | GitHub → Settings → Developer settings → Personal access tokens → `public_repo` scope |
| `ANTHROPIC_API_KEY` | Claude risk assessment + deploy recommendation | console.anthropic.com → API Keys |

Add to `aeon/backend/.env`:

```env
GITHUB_TOKEN=ghp_...
ANTHROPIC_API_KEY=sk-ant-...
```

Then recreate the backend:

```powershell
docker compose up -d backend
```

---

## Usage

1. Open **http://localhost:3000/blast**
2. Enter a public GitHub repo (e.g. `expressjs/express`)
3. Find a PR number: go to `github.com/{owner}/{repo}/pulls` and copy any PR number from the URL
4. Click **Analyze Blast Radius**

Progress streams in the left panel. When done:

- The **risk banner** at the top shows `HIGH / MEDIUM / LOW`, the deploy recommendation, and a checklist of what to verify
- The **radial graph** shows the full impact map — PR center → files → affected areas
- Click any node for details (file path, additions/deletions, risk level)
- Toggle between **Radial** (blast spreading outward) and **Force** (physics layout)

---

## Good demo PR

**`expressjs/express` — PR #7233** (`Upgrade content-disposition`)

This PR is ideal for demo because it touches 4 different impact categories:

| File | Category | Risk |
|---|---|---|
| `package.json` | Dependencies | HIGH |
| `lib/response.js` | Service | HIGH |
| `test/res.attachment.js` | Test | LOW |
| `test/res.download.js` | Test | LOW |
| `test/acceptance/downloads.js` | Test | LOW |
| `History.md` | Docs | LOW |

A dependency bump that ripples into core response handling + download tests — the kind of change where blast radius analysis matters most.

---

## Incident memory recall

Before the AI risk assessment, the PR is checked against **Aeon's incident memory** (the same ChromaDB store the AI Assistant writes to after every analysis). A past incident is recalled when:

- a changed filename literally appears in the incident's document, **or**
- the semantic similarity between the PR and the incident is ≥ 35%

Recalled incidents show up in three places:

1. A cyan **Incident Memory** banner under the risk banner — incident id, match %, shared files, past root cause
2. **Incident nodes** in the graph, linked to the PR with `RECALLS` edges (click for past root cause + fix)
3. The Claude risk prompt — so the narrative can say *"this matches incident #421"* and adjust the risk level

If ChromaDB is down or memory is empty, the analysis proceeds without recall (no errors).

---

## Impact categories

| Category | Color | What it means |
|---|---|---|
| PR | Green | The pull request being analyzed |
| File | Slate | A changed source file |
| Service | Orange | Core application/library code (`src/`, `lib/`, `app/`, monorepo packages) |
| Test | Purple | Test files (`test/`, `__tests__/`, `spec/`, `*.test.js`) |
| Config | Yellow | Config files (`.yml`, `.env`, `settings.py`) |
| Pipeline | Blue | CI/CD (`.github/workflows/`, `Jenkinsfile`, `.circleci/`) |
| Infrastructure | Pink | Docker, Kubernetes, Terraform |
| Dependencies | Red | Package manifests (`package.json`, `requirements.txt`, `go.mod`, lockfiles) |
| Docs | Slate | Markdown, RST, documentation folders |

---

## Risk levels

| Level | Meaning |
|---|---|
| HIGH | Core service code, dependencies, or infrastructure changed — production impact likely if something is wrong |
| MEDIUM | Config or pipeline changed — deployment behavior may differ |
| LOW | Only tests or docs changed — safe to merge, but verify tests pass |

---

## Service name inference

For monorepos (`packages/auth/src/index.js` → `auth`) and standard layouts (`src/middleware/logger.js` → `middleware`). Service nodes in the graph are deduplicated — if 5 files all belong to the `api` service, one `Service: api` node appears with `file_count: 5`.

---

## API endpoint

| Endpoint | Description |
|---|---|
| `GET /api/blast/stream?repo=&pr=` | SSE stream — progress steps, risk event, result graph |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `#N is an Issue, not a Pull Request` | GitHub issues and PRs share the same number sequence. Go to the repo's **Pull Requests** tab (not Issues) and use that number |
| PR not found | The repo might be private, or the PR was deleted. Only public repos are supported |
| Rate limit hit | Add `GITHUB_TOKEN` to `.env` and run `docker compose up -d backend` |
| Risk assessment missing | `ANTHROPIC_API_KEY` is not set. The graph still renders, but no AI narrative |
| Graph renders with no impact nodes | All changed files were docs or config — the PR has a LOW blast radius by design |
