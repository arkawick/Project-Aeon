# Code Provenance Graph

Answers the question: **"Why is this code the way it is?"**

Traces the full history of any public GitHub file — commits → pull requests → issues — then uses AI to explain the reasoning behind every change and write a narrative of the file's evolution.

---

## How it works

```
GitHub file path
      │
      ▼
Commit history (GitHub API)
      │
      ├──► Linked PRs (per commit)
      │         │
      │         └──► Linked Issues (from PR body)
      │
      ├──► Per-node AI reasoning  (claude-haiku — fast, per artifact)
      ├──► Evolution narrative    (claude-sonnet — holistic, full history)
      └──► Neo4j cache            (graph stored for instant replay)
```

Results are streamed live to the browser over SSE — you see progress in real time as commits, PRs, and issues are fetched.

---

## Prerequisites

| Requirement | Why | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Per-node "why" summaries + evolution narrative | console.anthropic.com → API Keys |
| `GITHUB_TOKEN` | 5000 req/hr instead of 60/hr (required for >5 commits) | GitHub → Settings → Developer settings → Personal access tokens → `public_repo` scope |
| Neo4j running | Graph caching (gracefully skipped if down) | Already in `docker-compose.yml` |

Add both to `aeon/backend/.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
```

Then restart the backend:

```powershell
docker compose restart backend
```

---

## Usage

1. Open **http://localhost:3000/provenance**
2. Enter a public GitHub repo (e.g. `facebook/react`)
3. Enter a file path (e.g. `packages/react/src/React.js`)
4. Choose how many commits to trace (5 = fast, 30 = thorough)
5. Click **Trace Provenance**

Progress steps stream in the left panel while the graph builds. When done:

- The **AI Evolution Narrative** banner appears above the graph — a 3–5 sentence story of why the file evolved
- Click any node to see its AI-generated "why" reasoning
- Click a **Commit** node to see the actual file diff (added/removed lines)
- Toggle between **Force** (physics layout) and **Timeline** (chronological) views

---

## Example repos to try

| Repo | File | What you'll learn |
|---|---|---|
| `facebook/react` | `packages/react/src/React.js` | How the public API surface evolved |
| `expressjs/express` | `lib/application.js` | Middleware architecture decisions |
| `psf/requests` | `src/requests/models.py` | HTTP model design history |
| `tiangolo/fastapi` | `fastapi/routing.py` | Routing system evolution |

---

## Graph nodes

| Node | Color | Meaning |
|---|---|---|
| File | Cyan | The file being traced |
| Commit | Slate | A git commit that touched this file |
| Pull Request | Green | A PR that included that commit |
| Issue | Amber | A GitHub issue referenced or closed by the PR |
| Developer | Purple | Author of the commit or PR opener |

## Graph edges

| Edge | Meaning |
|---|---|
| `MODIFIED_IN` | File → Commit |
| `AUTHORED_BY` | Commit → Developer |
| `PART_OF` | Commit → PullRequest |
| `OPENED` | Developer → PullRequest |
| `CLOSES` | PullRequest → Issue (explicit "closes #N") |
| `REFERENCES` | PullRequest → Issue (bare `#N` mention) |

---

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/provenance/stream?repo=&file_path=&max_commits=` | SSE stream — progress + result |
| `GET /api/provenance/cached?repo=&file_path=` | Return cached graph from Neo4j |
| `GET /api/provenance/diff?repo=&sha=` | Fetch real diff for a commit |

---

## Layout modes

**Force** (default) — physics simulation, nodes repel each other. Drag nodes to explore relationships. Best for understanding connections.

**Timeline** — commits ordered left→right by date on a horizontal axis. PRs float above their commits, issues above PRs, developers below. Best for understanding the sequence of changes over time.

Switch with the **Force / Timeline** buttons in the toolbar above the graph.

---

## Commit depth guide

| Setting | API calls | Time | When to use |
|---|---|---|---|
| 5 commits | ~10–20 | 5–10s | Quick demo |
| 10 commits | ~20–50 | 10–20s | Most cases |
| 20 commits | ~40–100 | 20–40s | Deep research |
| 30 commits | ~60–150 | 30–60s | Full history audit (needs `GITHUB_TOKEN`) |

Each commit can trigger 1 PR lookup + up to 4 issue lookups. The unauthenticated rate limit of 60 req/hr is exhausted in ~3 runs at depth 10. Add `GITHUB_TOKEN` to avoid this.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `GitHub API rate limit exceeded` | Add `GITHUB_TOKEN` to `.env` and restart backend. The error message shows the exact reset time. |
| Graph loads but no "why" summaries | `ANTHROPIC_API_KEY` is missing or invalid |
| Evolution narrative missing | Same as above — narrative also requires the API key |
| Diff not loading on commit click | Commit diff is a separate GitHub API call; rate limit may be hit even with a token if tracing a very large repo |
| Neo4j cache errors in logs | Neo4j is down — provenance still works, graph just won't be cached for replay |
| File not found / repo private | Only public repos are supported (no auth token is sent to GitHub for repo access) |
| Long error text not wrapping in UI | Known display issue on very long URLs — the error is still readable by scrolling |
