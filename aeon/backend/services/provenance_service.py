"""
Code Provenance Graph Service
=============================
Given a public GitHub repo + file path, traces WHY the code is the way it is by
walking commit history → linked PRs → linked Issues and asking Claude to summarise
the reasoning behind each change.

Graph schema stored in Neo4j:
  (File)-[:MODIFIED_IN]->(Commit)-[:AUTHORED_BY]->(Developer)
  (Commit)-[:PART_OF]->(PullRequest)-[:CLOSES|REFERENCES]->(Issue)
  (Developer)-[:OPENED]->(PullRequest)
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, AsyncIterator

import httpx
import anthropic


GH_API     = "https://api.github.com"
GH_GRAPHQL = "https://api.github.com/graphql"
_ISSUE_RE  = re.compile(r"(?:closes?|fixes?|resolves?|refs?|references?)\s*#(\d+)", re.IGNORECASE)
_CLOSES_RE = re.compile(r"(?:closes?|fixes?|resolves?)\s*#(\d+)", re.IGNORECASE)
_NUM_RE    = re.compile(r"#(\d+)")

NODE_COLORS = {
    "File":        "#9cdef2",   # aeon cyan
    "Commit":      "#64748b",   # slate
    "PullRequest": "#22c55e",   # green
    "Issue":       "#f59e0b",   # amber
    "Developer":   "#a855f7",   # purple
}


def _gh_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _node(nid: str, ntype: str, label: str, **extra) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "label": label, "color": NODE_COLORS[ntype], **extra}


def _edge(source: str, target: str, rel: str) -> dict[str, Any]:
    return {"source": source, "target": target, "type": rel}


async def _gh_get(client: httpx.AsyncClient, endpoint: str, **params) -> Any:
    headers = _gh_headers()
    resp = await client.get(
        f"{GH_API}{endpoint}",
        headers=headers,
        params=params,
        timeout=15.0,
    )
    if resp.status_code == 404:
        return None

    if resp.status_code in (403, 429):
        has_token = bool(os.getenv("GITHUB_TOKEN", "").strip())
        remaining  = resp.headers.get("X-RateLimit-Remaining", "?")
        reset_ts   = resp.headers.get("X-RateLimit-Reset", "")
        retry_after = resp.headers.get("Retry-After", "")

        import datetime
        reset_str = ""
        if reset_ts:
            try:
                reset_str = f" Resets at {datetime.datetime.utcfromtimestamp(int(reset_ts)).strftime('%H:%M UTC')}."
            except Exception:
                pass

        if not has_token:
            raise RuntimeError(
                "GitHub API rate limit exceeded — you are unauthenticated (60 req/hr). "
                "Add GITHUB_TOKEN to aeon/backend/.env, then run: docker compose restart backend."
                + reset_str
            )

        if retry_after:
            raise RuntimeError(
                f"GitHub secondary rate limit hit (too many requests in a short burst). "
                f"Wait {retry_after}s before retrying, or reduce commit depth."
                + reset_str
            )

        raise RuntimeError(
            f"GitHub API rate limit exceeded — authenticated but quota exhausted "
            f"(remaining: {remaining}).{reset_str} "
            "Your token is loaded but the 5000/hr quota is used up. Try again later or use a different token."
        )

    resp.raise_for_status()
    return resp.json()


async def _ai_why(items: list[dict[str, str]]) -> dict[str, str]:
    """
    Ask Claude for a 1–2 sentence 'why' summary for each commit/PR/issue.
    Returns {item_id: why_summary}.
    """
    if not items:
        return {}

    from core import llm

    if not llm.llm_available():
        return {item["id"]: item.get("raw", "No AI summary (no LLM key set)") for item in items}

    prompt_lines = ["For each item below, give a concise 1–2 sentence answer to: 'WHY was this change made?'",
                    "Focus on intent and reasoning, not description. Reply in this exact format:",
                    "ID: <id>",
                    "WHY: <your 1-2 sentence reasoning>",
                    "---", ""]

    for item in items:
        prompt_lines.append(f"ID: {item['id']}")
        prompt_lines.append(f"Type: {item['type']}")
        prompt_lines.append(f"Content: {item['raw'][:600]}")
        prompt_lines.append("---")

    text = await llm.complete(system="", user="\n".join(prompt_lines), max_tokens=1500)
    if not text:
        return {item["id"]: item.get("raw", "")[:120] for item in items}

    result: dict[str, str] = {}
    for item in items:
        pattern = rf"ID:\s*{re.escape(item['id'])}.*?WHY:\s*(.+?)(?=\n---|\nID:|\Z)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            result[item["id"]] = m.group(1).strip()
        else:
            result[item["id"]] = item.get("raw", "")[:120]
    return result


async def _ai_narrative(repo: str, file_path: str, ai_items: list[dict]) -> str:
    """
    Send the full commit/PR/issue history to Claude in one shot and get back
    a 3–5 sentence story explaining WHY this file evolved the way it did.
    """
    from core import llm

    if not llm.llm_available() or not ai_items:
        return ""

    history_lines = []
    for item in ai_items:
        history_lines.append(f"[{item['type']}] {item['raw'][:300]}")

    prompt = f"""You are analyzing the full change history of a source code file to explain its evolution.

Repository: {repo}
File: {file_path}

Complete change history (newest first):
{chr(10).join(history_lines)}

Write a 3–5 sentence narrative that answers: "Why is this file the way it is today?"

Cover:
1. What this file's core purpose is (inferred from the changes)
2. The key phases of evolution (e.g. "initial implementation → security hardening → performance rewrite")
3. The main problems or decisions that shaped its current structure
4. Any notable patterns (e.g. frequent bug fixes in one area, a major refactor, recurring contributors)

Be specific — reference actual PR numbers, issue numbers, and developer names where relevant.
Write in past tense. Focus on WHY, not WHAT. No bullet points, just flowing prose."""

    text = await llm.complete(system="", user=prompt, max_tokens=400)
    return (text or "").strip()


async def fetch_commit_diff(repo: str, sha: str) -> dict:
    """
    Fetch the actual file diff for a commit from GitHub.
    Returns {sha, stats, files: [{filename, additions, deletions, patch}]}
    """
    owner_repo = repo.strip("/").replace("https://github.com/", "")
    parts = owner_repo.split("/")
    if len(parts) < 2:
        return {"error": "Invalid repo"}

    owner, repo_name = parts[0], parts[1]
    async with httpx.AsyncClient() as client:
        data = await _gh_get(client, f"/repos/{owner}/{repo_name}/commits/{sha}")
    if not data:
        return {"error": "Commit not found"}

    files = []
    for f in (data.get("files") or [])[:10]:
        files.append({
            "filename":  f.get("filename", ""),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "status":    f.get("status", ""),
            "patch":     f.get("patch", "")[:2000],
        })

    return {
        "sha":   sha,
        "stats": data.get("stats", {}),
        "files": files,
    }


_HISTORY_QUERY = """
query($owner: String!, $name: String!, $path: String!, $n: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: $n, path: $path) {
            nodes {
              oid
              message
              committedDate
              author { name user { login avatarUrl } }
              associatedPullRequests(first: 2) {
                nodes {
                  number title body url state
                  author { login }
                  closingIssuesReferences(first: 4) {
                    nodes { number title body url state }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


async def _fetch_history_graphql(
    client: httpx.AsyncClient,
    owner: str,
    repo_name: str,
    file_path: str,
    max_commits: int,
) -> list[dict[str, Any]] | None:
    """
    Fast path: ONE GraphQL request fetches commits + associated PRs + closing
    issues, replacing ~1 + N + N*4 REST calls. Requires GITHUB_TOKEN.
    Returns normalized commits, [] if the file has no history, None if the
    repo doesn't exist / isn't accessible.
    """
    token = os.getenv("GITHUB_TOKEN", "").strip()
    resp = await client.post(
        GH_GRAPHQL,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "query": _HISTORY_QUERY,
            "variables": {"owner": owner, "name": repo_name, "path": file_path, "n": max_commits},
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))

    repo_data = (payload.get("data") or {}).get("repository")
    if not repo_data or not repo_data.get("defaultBranchRef"):
        return None

    commits: list[dict[str, Any]] = []
    for c in repo_data["defaultBranchRef"]["target"]["history"]["nodes"]:
        author = c.get("author") or {}
        user = author.get("user") or {}
        prs = []
        for pr in (c.get("associatedPullRequests") or {}).get("nodes") or []:
            closing = (pr.get("closingIssuesReferences") or {}).get("nodes") or []
            prs.append({
                "number": pr["number"],
                "title":  pr.get("title", ""),
                "body":   pr.get("body") or "",
                "url":    pr.get("url", ""),
                "state":  (pr.get("state") or "").lower(),
                "user":   (pr.get("author") or {}).get("login", ""),
                "closing_issues": [
                    {
                        "number": i["number"],
                        "title":  i.get("title", ""),
                        "body":   i.get("body") or "",
                        "url":    i.get("url", ""),
                        "state":  (i.get("state") or "").lower(),
                    }
                    for i in closing
                ],
            })
        commits.append({
            "sha":          c["oid"],
            "message":      c.get("message", ""),
            "date":         (c.get("committedDate") or "")[:10],
            "author_login": user.get("login") or author.get("name") or "unknown",
            "avatar_url":   user.get("avatarUrl", ""),
            "prs":          prs,
        })
    return commits


async def _fetch_history_rest(
    client: httpx.AsyncClient,
    owner: str,
    repo_name: str,
    file_path: str,
    max_commits: int,
) -> list[dict[str, Any]] | None:
    """
    Fallback path (no token / GraphQL failed): commit list in one call, then
    all per-commit PR lookups in parallel instead of serially.
    """
    commits_data = await _gh_get(
        client, f"/repos/{owner}/{repo_name}/commits",
        path=file_path, per_page=max_commits,
    )
    if not commits_data:
        return None

    sem = asyncio.Semaphore(8)

    async def _prs_for(sha: str) -> list[dict]:
        async with sem:
            try:
                return await _gh_get(client, f"/repos/{owner}/{repo_name}/commits/{sha}/pulls") or []
            except Exception:
                return []

    prs_lists = await asyncio.gather(*[_prs_for(c["sha"]) for c in commits_data])

    commits: list[dict[str, Any]] = []
    for c, prs_raw in zip(commits_data, prs_lists):
        commits.append({
            "sha":          c["sha"],
            "message":      c["commit"]["message"],
            "date":         c["commit"]["author"]["date"][:10],
            "author_login": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
            "avatar_url":   (c.get("author") or {}).get("avatar_url", ""),
            "prs": [
                {
                    "number": p["number"],
                    "title":  p.get("title", ""),
                    "body":   p.get("body") or "",
                    "url":    p.get("html_url", ""),
                    "state":  p.get("state", ""),
                    "user":   (p.get("user") or {}).get("login", ""),
                    "closing_issues": [],
                }
                for p in prs_raw
            ],
        })
    return commits


async def build_provenance_graph(
    repo: str,
    file_path: str,
    max_commits: int = 12,
) -> AsyncIterator[dict[str, Any]]:
    """
    Async generator — yields progress events then the final graph.
    Event shapes:
      {type: "step",   message: str}
      {type: "result", nodes: [...], edges: [...], meta: {...}}
      {type: "error",  message: str}
    """
    owner_repo = repo.strip("/").replace("https://github.com/", "")
    parts = owner_repo.split("/")
    if len(parts) < 2:
        yield {"type": "error", "message": f"Invalid repo format: '{repo}'. Use 'owner/repo'."}
        return

    owner, repo_name = parts[0], parts[1]
    file_path = file_path.lstrip("/")
    file_id = f"{owner}/{repo_name}/{file_path}"

    nodes: dict[str, dict]  = {}
    edges: list[dict]        = []
    seen_prs: set[int]       = set()
    seen_issues: set[int]    = set()
    seen_devs: set[str]      = set()
    ai_items: list[dict]     = []

    # ── File node ─────────────────────────────────────────────────────
    nodes[file_id] = _node(
        file_id, "File", file_path.split("/")[-1],
        full_path=file_path, repo=f"{owner}/{repo_name}",
        why="This is the file whose change history is being traced.",
    )

    def _add_issue_node(pr_id: str, issue: dict, rel: str):
        issue_id = f"issue:{issue['number']}"
        nodes[issue_id] = _node(
            issue_id, "Issue", f"#{issue['number']}",
            number=issue["number"],
            title=issue.get("title", ""),
            url=issue.get("url", ""),
            state=issue.get("state", ""),
        )
        edges.append(_edge(pr_id, issue_id, rel))
        ai_items.append({
            "id": issue_id, "type": "Issue",
            "raw": f"Issue #{issue['number']}: {issue.get('title','')}. {(issue.get('body') or '')[:400]}",
        })

    async with httpx.AsyncClient() as client:
        # ── 1. Commit history + linked PRs (GraphQL fast path) ────────
        has_token = bool(os.getenv("GITHUB_TOKEN", "").strip())
        commits = None
        if has_token:
            yield {"type": "step", "message": f"Fetching history for `{file_path}` via GraphQL (single request)…"}
            try:
                commits = await _fetch_history_graphql(client, owner, repo_name, file_path, max_commits)
            except Exception as exc:
                yield {"type": "step", "message": f"GraphQL unavailable ({exc}) — falling back to parallel REST…"}
                commits = await _fetch_history_rest(client, owner, repo_name, file_path, max_commits)
        else:
            yield {"type": "step", "message": f"Fetching history for `{file_path}` via parallel REST (add GITHUB_TOKEN for the 1-request GraphQL fast path)…"}
            commits = await _fetch_history_rest(client, owner, repo_name, file_path, max_commits)

        if not commits:
            yield {"type": "error", "message": "File not found or repo is private / doesn't exist."}
            return

        yield {"type": "step", "message": f"Found {len(commits)} commits with linked PRs. Building graph…"}

        # ── 2. Build graph from normalized history ────────────────────
        # (pr_id, issue_number, rel) still needing a REST lookup
        pending_issue_refs: list[tuple[str, int, str]] = []

        for c in commits:
            short = c["sha"][:7]
            commit_id = f"commit:{short}"
            nodes[commit_id] = _node(
                commit_id, "Commit", short,
                sha=c["sha"], message=c["message"].split("\n")[0],
                author=c["author_login"], date=c["date"],
            )
            edges.append(_edge(file_id, commit_id, "MODIFIED_IN"))
            ai_items.append({
                "id": commit_id, "type": "Commit",
                "raw": f"Commit {short} by {c['author_login']}: {c['message'].split(chr(10))[0]}",
            })

            dev_id = f"dev:{c['author_login']}"
            if c["author_login"] not in seen_devs:
                seen_devs.add(c["author_login"])
                nodes[dev_id] = _node(dev_id, "Developer", c["author_login"], avatar_url=c["avatar_url"])
            edges.append(_edge(commit_id, dev_id, "AUTHORED_BY"))

            for pr_data in c["prs"]:
                pr_num = pr_data["number"]
                if pr_num in seen_prs:
                    # still connect this commit to the already-known PR
                    edges.append(_edge(commit_id, f"pr:{pr_num}", "PART_OF"))
                    continue
                seen_prs.add(pr_num)

                pr_id = f"pr:{pr_num}"
                nodes[pr_id] = _node(
                    pr_id, "PullRequest", f"PR #{pr_num}",
                    number=pr_num,
                    title=pr_data["title"],
                    url=pr_data["url"],
                    state=pr_data["state"],
                    user=pr_data["user"],
                )
                edges.append(_edge(commit_id, pr_id, "PART_OF"))
                if pr_data["user"]:
                    dev_node_id = f"dev:{pr_data['user']}"
                    if pr_data["user"] not in seen_devs:
                        seen_devs.add(pr_data["user"])
                        nodes[dev_node_id] = _node(dev_node_id, "Developer", pr_data["user"])
                    edges.append(_edge(dev_node_id, pr_id, "OPENED"))

                ai_items.append({
                    "id": pr_id, "type": "PullRequest",
                    "raw": f"PR #{pr_num}: {pr_data['title']}. {pr_data['body'][:400]}",
                })

                # Closing issues already delivered by GraphQL — no extra calls
                for issue in pr_data["closing_issues"]:
                    if issue["number"] in seen_issues or issue["number"] == pr_num:
                        continue
                    seen_issues.add(issue["number"])
                    _add_issue_node(pr_id, issue, "CLOSES")

                # Keyword-linked issues from the PR body (closes/fixes/refs #N).
                # Bare #N mentions are only used as a fallback — they were too noisy.
                pr_body = pr_data["body"]
                issue_nums = [int(n) for n in _ISSUE_RE.findall(pr_body)]
                if not issue_nums:
                    issue_nums = [int(n) for n in _NUM_RE.findall(pr_body) if int(n) < 100000][:2]
                closes_nums = {int(n) for n in _CLOSES_RE.findall(pr_body)}
                for issue_num in list(dict.fromkeys(issue_nums))[:4]:
                    if issue_num in seen_issues or issue_num == pr_num:
                        continue
                    seen_issues.add(issue_num)
                    rel = "CLOSES" if issue_num in closes_nums else "REFERENCES"
                    pending_issue_refs.append((pr_id, issue_num, rel))

        # ── 3. Fetch referenced issues in parallel ────────────────────
        if pending_issue_refs:
            pending_issue_refs = pending_issue_refs[:20]
            yield {"type": "step", "message": f"Fetching {len(pending_issue_refs)} referenced issues in parallel…"}
            sem = asyncio.Semaphore(8)

            async def _fetch_issue(num: int):
                async with sem:
                    try:
                        return await _gh_get(client, f"/repos/{owner}/{repo_name}/issues/{num}")
                    except Exception:
                        return None

            issue_results = await asyncio.gather(*[_fetch_issue(num) for _, num, _ in pending_issue_refs])
            for (pr_id, issue_num, rel), issue_data in zip(pending_issue_refs, issue_results):
                if not issue_data or "pull_request" in issue_data:
                    continue
                _add_issue_node(pr_id, {
                    "number": issue_num,
                    "title":  issue_data.get("title", ""),
                    "body":   issue_data.get("body") or "",
                    "url":    issue_data.get("html_url", ""),
                    "state":  issue_data.get("state", ""),
                }, rel)

    # ── 4+5. AI reasoning + evolution narrative (concurrent) ─────────
    yield {"type": "step", "message": f"Generating AI reasoning for {len(ai_items)} artifacts + evolution narrative…"}
    why_map, narrative = await asyncio.gather(
        _ai_why(ai_items[:30]),
        _ai_narrative(repo=f"{owner}/{repo_name}", file_path=file_path, ai_items=ai_items[:30]),
    )
    for node_id, why in why_map.items():
        if node_id in nodes:
            nodes[node_id]["why"] = why
    yield {"type": "narrative", "text": narrative}

    # ── 6. Emit result ────────────────────────────────────────────────
    yield {
        "type":  "result",
        "nodes": list(nodes.values()),
        "edges": edges,
        "meta":  {
            "repo":        f"{owner}/{repo_name}",
            "file":        file_path,
            "commits":     len([n for n in nodes.values() if n["type"] == "Commit"]),
            "prs":         len([n for n in nodes.values() if n["type"] == "PullRequest"]),
            "issues":      len([n for n in nodes.values() if n["type"] == "Issue"]),
            "developers":  len([n for n in nodes.values() if n["type"] == "Developer"]),
        },
    }
