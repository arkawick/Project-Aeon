# Co-Change Coupling Analyzer

Answers the question: **"Which files change together — and which one did this PR forget?"**

Mines a repo's recent commit history to find file pairs that are repeatedly modified in the same commit. This reveals *hidden coupling* that no import graph shows: if `auth.py` and `session.py` change together 80% of the time and someone edits only one of them, that's a likely missed change.

---

## How it works

```
GitHub repo
    │
    ▼
Last N commits (list, 1 request)
    │
    ├──► Per-commit file lists (parallel, 10 at a time)
    ├──► Skip merge commits + bulk changes (> 40 files)
    ├──► Count pair co-occurrences
    │        score = co_changes / min(changes_a, changes_b)
    └──► Claude insight on what the strongest couplings mean
```

Pairs must co-change **at least twice** to appear. Results stream live over SSE.

---

## Usage

1. Open **http://localhost:3000/cochange**
2. Enter a public GitHub repo (e.g. `expressjs/express`)
3. Pick a history depth (50 / 100 / 200 commits)
4. Optionally enter a **focus file** to see only its coupling partners
5. Click **Analyze Coupling**

The graph shows files as nodes (size = how often the file changes, color = top-level directory) and couplings as edges (thickness/color = coupling strength). Click a file to see its partners ranked by strength.

---

## Reading the score

| Coupling | Color | Meaning |
|---|---|---|
| ≥ 70% | Red | Tight coupling — these files are effectively one module |
| 40–70% | Amber | Moderate — probably related, check before merging one alone |
| < 40% | Slate | Loose — occasional co-change |

Healthy couplings exist (code + its test, workflow files maintained together). The risky ones are two *seemingly unrelated* files moving in lockstep — the AI insight banner calls these out.

---

## Prerequisites

| Requirement | Why |
|---|---|
| `GITHUB_TOKEN` | Each commit needs one detail request — 100 commits ≈ 101 requests. Without a token, depth is capped at 30 commits |
| `ANTHROPIC_API_KEY` | AI coupling insight (analysis still works without it) |

---

## API endpoint

| Endpoint | Description |
|---|---|
| `GET /api/cochange/stream?repo=&commits=&file_path=` | SSE stream — progress steps, AI insight, coupling graph |
