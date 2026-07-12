# Predictive Merge Gate

Answers the question: **"Is this PR's build going to fail — *before* I run it?"**

Given any public GitHub pull request, Aeon forecasts CI failure risk by fusing signals it already computes — incident memory, co-change coupling, PR shape, and the repo's current CI state — into a **PASS / CAUTION / BLOCK** verdict with a probability, a confidence level, and a "run these before merge" checklist. It builds nothing; it reasons over the repo's own history plus live CI.

This turns Aeon from *reactive* ("why did it fail?") into *predictive* ("it's about to fail, here's where").

---

## How it works

```
PR number
    │
    ▼
GitHub PR API → changed files + head commit SHA
    │
    ├──► Signal 1  Incident memory   — do these files resemble PAST failed incidents?   (ChromaDB recall)
    ├──► Signal 2  Hanging points     — per-file git history: did the PR change a file    (targeted co-change)
    │                                   but OMIT a partner it historically changes WITH?
    ├──► Signal 3  PR shape           — source without tests, big diff, dep/lockfile churn (from the PR files)
    ├──► Signal 4  Risk surface       — how many changed files are HIGH-risk classes?      (Blast classifier)
    │
    ├──► Ground truth   Current CI check-runs on the head commit (failing check → BLOCK)
    │
    └──► Blend → probability → verdict + confidence + LLM narrative + must-test list
```

Everything streams live to the browser (SSE), the same pattern as Blast Radius and Co-Change. It reuses Blast Radius's file classifier + incident recall and mines co-change directly — no new infrastructure.

---

## The score

```
fail_score = 0.30·memory + 0.25·hanging + 0.25·shape + 0.20·risk     (each signal 0..1)

Ground-truth override:
  CI already FAILING  → probability = max(score, 85), verdict BLOCK
  CI currently GREEN  → probability = min(score, 25)
  pending / none      → probability = score
```

`probability ≥ 60 → BLOCK`, `≥ 35 → CAUTION`, else `PASS`. Weights and the raw per-signal values are returned in the result `meta` for transparency.

### Confidence
How much evidence actually fired — so a weak 45% reads differently than a strong one:

| Confidence | When |
|---|---|
| **high** | live CI ground truth exists, **or** ≥ 3 signals fired |
| **medium** | exactly 2 signals fired |
| **low** | ≤ 1 signal fired (little history for this repo — treat as a hint, not a gate) |

---

## The signals in detail

### 1. Incident memory (weight 0.30)
Reuses Blast Radius's `_search_incident_memory` — vector search over Aeon's ChromaDB incident store. A literal shared filename with a past incident boosts the signal (+0.15). *"This mirrors `inc_demo_421`, which broke `lib/response.js`."*

### 2. Hanging points (weight 0.25) — the strongest pre-build tell
**Targeted** co-change: for each changed source/test file, Aeon fetches that file's *own* commit history (`/commits?path=<file>`), then looks at what co-changed with it. If the PR touches a file but omits a partner it historically changes with (≥ 3 times, ≥ 50% coupling), that's a hanging point:

> *"You changed `lib/response.js` but not `test/res.download.js` — they change together 9× at 90% coupling. That omission usually breaks CI."*

This is what makes the gate fire on **any** real PR, not just ones that happen to appear in a global commit window.

### 3. PR shape (weight 0.25) — always available
Cheap, structural signals computed from the PR files, present even with zero history:
- **source changed but no tests updated** (+0.40) — the classic failure predictor
- **large diff** > 800 lines (+0.35) / sizable > 300 (+0.20)
- **dependency manifest changed** (+0.20)
- **infra/config changed** (+0.15)

The specific reasons are surfaced as chips in the UI.

### 4. Risk surface (weight 0.20)
Fraction of changed files in HIGH-risk classes (Dependencies / Config / Infrastructure / Service), via Blast Radius's `_classify_file`.

### Ground truth: CI check-runs
Reads the PR head commit's existing check-runs (`/commits/{sha}/check-runs`). A check **already failing** forces a high-confidence **BLOCK** (reality beats prediction); **all-green** dampens the estimate. This is why a merged PR whose CI passed correctly shows **PASS** even if it resembles a past failure.

---

## Prerequisites

| Requirement | Why | Where |
|---|---|---|
| `GITHUB_TOKEN` | Targeted co-change makes several API calls per PR — 5000 req/hr needed | GitHub → Developer settings → tokens (`public_repo`) |
| LLM key (Azure **or** Anthropic) | Narrative + must-test list (a deterministic narrative is used without one) | see `aeon/backend/.env.example` |

Add to `aeon/backend/.env`, then `docker compose up -d backend`.

---

## Usage

1. Open **http://localhost:3000/predict** (sidebar → **Merge Gate**)
2. Enter a public repo (e.g. `expressjs/express`) and a PR number
3. Click **Forecast**

You get: a circular **fail-risk gauge**, the **verdict + confidence** chip, the **CI status** line, a **signal breakdown** (four bars, with weights), **hanging points**, **past incidents it resembles**, and a **run-these-before-merge** checklist.

---

## Demo notes

- **Best "it's risky" beat:** an **open** PR that resembles a past failure and/or has hanging points and whose CI hasn't run yet → the prediction signals drive a **CAUTION / BLOCK** with the narrative explaining exactly why.
- **`expressjs/express` PR 7233** now returns **PASS (25%)** — it's a *merged* PR whose 30 CI checks passed, so the ground-truth prior correctly overrides the historical resemblance to `inc_demo_421`. Great for showing the gate is honest, not for the "about to fail" beat.
- If CI already **failed** on a PR, the gate shows a high-confidence **BLOCK** citing the failing check by name.

---

## Verdicts

| Verdict | Probability | Meaning |
|---|---|---|
| **BLOCK** | ≥ 60% (or a CI check already failing) | Likely to fail — fix the flagged points before merge |
| **CAUTION** | 35–59% | Meaningful risk — run the must-test list first |
| **PASS** | < 35% | Looks safe — but still verify anything flagged |

---

## API endpoint

| Endpoint | Description |
|---|---|
| `GET /api/predict/stream?repo=&pr=&commits=` | SSE stream — progress steps, a `signals` event, then the final `result` (verdict, probability, confidence, hanging points, memory matches, CI state, must-test). `commits` (default 60) bounds co-change depth. |

Event types: `step`, `signals`, `result`, `error`.

---

## Honest limitations

- It predicts **correlation with the repo's own history + current CI**, not an actual compile — it will not catch a brand-new syntax error it has never seen. It catches recurring failure patterns, coupling violations, risky shapes, and known-bad CI.
- Accuracy scales with incident history and commit depth for that repo; on a thin repo the confidence will read **low** — surfaced, not hidden.
- It's a **pre-flight risk gate**, not a guarantee — same honesty stance as Blast Radius.

---

## Files

| File | Role |
|---|---|
| `aeon/backend/services/predict_service.py` | Signal computation + fusion + narrative |
| `aeon/backend/api/predict.py` | `GET /api/predict/stream` SSE route |
| `aeon/frontend/src/pages/Predict.jsx` | Gauge + signals + hanging points UI |
