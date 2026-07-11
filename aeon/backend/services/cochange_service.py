"""
Co-Change Coupling Analyzer
===========================
Mines recent commit history to find file pairs that are repeatedly modified
together — hidden coupling that no import graph shows. If `auth.py` and
`session.py` change together 80% of the time and a PR touches only one of
them, that's a likely missed change.

score = co_changes / min(changes_a, changes_b)   (coupling confidence, 0..1)

Graph schema:
  (File)-[:COCHANGES {co_count, score}]->(File)
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from typing import Any, AsyncIterator

import anthropic
import httpx

GH_API = "https://api.github.com"

# Commits touching more files than this are treated as bulk changes
# (mass renames, formatting sweeps) and skipped for pair counting.
MAX_FILES_PER_COMMIT = 40

DIR_PALETTE = [
    "#f97316", "#22c55e", "#a855f7", "#3b82f6",
    "#eab308", "#ec4899", "#14b8a6", "#94a3b8",
]


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _gh_get(client: httpx.AsyncClient, endpoint: str, **params) -> Any:
    resp = await client.get(f"{GH_API}{endpoint}", headers=_gh_headers(), params=params, timeout=15.0)
    if resp.status_code == 404:
        return None
    if resp.status_code in (403, 429):
        if not os.getenv("GITHUB_TOKEN", "").strip():
            raise RuntimeError(
                "GitHub rate limit — add GITHUB_TOKEN to aeon/backend/.env and run: docker compose up -d backend."
            )
        raise RuntimeError("GitHub rate limit exhausted (authenticated). Try again later or lower the commit depth.")
    resp.raise_for_status()
    return resp.json()


def _dir_color(path: str) -> str:
    top = path.split("/")[0]
    h = 0
    for ch in top:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return DIR_PALETTE[h % len(DIR_PALETTE)]


async def _ai_insight(repo: str, pairs: list[dict], commits_analyzed: int) -> str:
    """One short Claude read on what the strongest couplings mean."""
    from core import llm

    if not llm.llm_available() or not pairs:
        return ""

    pair_lines = "\n".join(
        f"  - {p['a']} <-> {p['b']}: changed together {p['co_count']}x "
        f"(coupling {p['score']:.0%}; individually changed {p['count_a']}x / {p['count_b']}x)"
        for p in pairs[:12]
    )
    prompt = f"""You are a senior engineer reviewing change-coupling data mined from git history.

Repository: {repo}
Commits analyzed: {commits_analyzed}
Strongest co-change couplings (files that keep changing in the same commit):
{pair_lines}

In 2-4 sentences, explain what this coupling reveals: which files form hidden modules,
which couplings look healthy (e.g. code + its test) vs. risky (e.g. two unrelated services
moving in lockstep), and the single most important thing a developer should watch out for
when editing one of these files. Reference actual filenames. Plain prose, no bullets."""

    text = await llm.complete(system="", user=prompt, max_tokens=400)
    return (text or "").strip()


async def build_cochange_graph(
    repo: str,
    max_commits: int = 100,
    focus_file: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """
    Async generator — yields progress events then the final coupling graph.
    Event shapes:
      {type: "step",    message: str}
      {type: "insight", text: str}
      {type: "result",  nodes: [...], edges: [...], meta: {...}}
      {type: "error",   message: str}
    """
    owner_repo = repo.strip("/").replace("https://github.com/", "")
    parts = owner_repo.split("/")
    if len(parts) < 2:
        yield {"type": "error", "message": f"Invalid repo '{repo}'. Use owner/repo format."}
        return
    owner, repo_name = parts[0], parts[1]

    has_token = bool(os.getenv("GITHUB_TOKEN", "").strip())
    if not has_token and max_commits > 30:
        max_commits = 30
        yield {"type": "step", "message": "No GITHUB_TOKEN — depth limited to 30 commits (60 req/hr unauthenticated)."}

    async with httpx.AsyncClient() as client:
        # ── 1. Commit list ────────────────────────────────────────────
        yield {"type": "step", "message": f"Fetching last {max_commits} commits from {owner}/{repo_name}…"}
        commit_list: list[dict] = []
        page = 1
        while len(commit_list) < max_commits:
            batch = await _gh_get(
                client, f"/repos/{owner}/{repo_name}/commits",
                per_page=min(100, max_commits - len(commit_list)), page=page,
            )
            if not batch:
                break
            commit_list.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        if not commit_list:
            yield {"type": "error", "message": f"No commits found — is {owner}/{repo_name} a public repo?"}
            return

        # ── 2. Per-commit file lists, fetched in parallel ─────────────
        yield {"type": "step", "message": f"Fetching file lists for {len(commit_list)} commits in parallel…"}
        sem = asyncio.Semaphore(10)

        async def _files_for(sha: str) -> tuple[list[str], int]:
            async with sem:
                try:
                    detail = await _gh_get(client, f"/repos/{owner}/{repo_name}/commits/{sha}")
                except Exception:
                    return [], 0
                if not detail:
                    return [], 0
                files = [f.get("filename", "") for f in (detail.get("files") or [])]
                return [f for f in files if f], len(detail.get("parents") or [])

        results = await asyncio.gather(*[_files_for(c["sha"]) for c in commit_list])

    # ── 3. Count co-occurrences ───────────────────────────────────────
    yield {"type": "step", "message": "Mining co-change patterns…"}
    file_counts: Counter = Counter()
    pair_counts: Counter = Counter()
    commits_used = 0

    for files, parent_count in results:
        if not files or parent_count > 1:   # skip merge commits
            continue
        fs = sorted(set(files))
        commits_used += 1
        for f in fs:
            file_counts[f] += 1
        if 2 <= len(fs) <= MAX_FILES_PER_COMMIT:
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    pair_counts[(fs[i], fs[j])] += 1

    pairs = []
    for (a, b), co in pair_counts.items():
        if co < 2:
            continue
        score = co / min(file_counts[a], file_counts[b])
        pairs.append({
            "a": a, "b": b,
            "co_count": co,
            "count_a": file_counts[a],
            "count_b": file_counts[b],
            "score": round(score, 3),
        })
    pairs.sort(key=lambda p: (p["co_count"], p["score"]), reverse=True)

    focus = focus_file.strip().lstrip("/")
    if focus:
        pairs = [p for p in pairs if p["a"].endswith(focus) or p["b"].endswith(focus)]
    pairs = pairs[:60]

    if not pairs:
        hint = f"No files co-changed with '{focus}' at least twice." if focus else \
               "No file pairs changed together at least twice in this window."
        yield {"type": "error", "message": f"{hint} Try a deeper commit window."}
        return

    yield {"type": "step", "message": f"Found {len(pairs)} coupled pairs across {commits_used} commits."}

    # ── 4. Build graph ────────────────────────────────────────────────
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for p in pairs:
        for path in (p["a"], p["b"]):
            if path not in nodes:
                nodes[path] = {
                    "id": path,
                    "type": "File",
                    "label": path.split("/")[-1],
                    "full_path": path,
                    "changes": file_counts[path],
                    "color": _dir_color(path),
                }
        edges.append({
            "source": p["a"], "target": p["b"], "type": "COCHANGES",
            "co_count": p["co_count"], "score": p["score"],
        })

    # ── 5. AI insight ─────────────────────────────────────────────────
    yield {"type": "step", "message": "Generating AI coupling insight…"}
    try:
        insight = await _ai_insight(f"{owner}/{repo_name}", pairs, commits_used)
    except Exception:
        insight = ""
    if insight:
        yield {"type": "insight", "text": insight}

    yield {
        "type":  "result",
        "nodes": list(nodes.values()),
        "edges": edges,
        "meta": {
            "repo":             f"{owner}/{repo_name}",
            "commits_analyzed": commits_used,
            "files_seen":       len(file_counts),
            "pairs_found":      len(pairs),
            "focus":            focus,
            "top_pairs":        pairs[:8],
        },
    }
