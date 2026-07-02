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


GH_API = "https://api.github.com"
_ISSUE_RE = re.compile(r"(?:closes?|fixes?|resolves?|refs?|references?)\s*#(\d+)", re.IGNORECASE)
_NUM_RE   = re.compile(r"#(\d+)")

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

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {item["id"]: item.get("raw", "No AI summary (ANTHROPIC_API_KEY not set)") for item in items}

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

    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
    )
    text = msg.content[0].text

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
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not ai_items:
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

    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


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

    async with httpx.AsyncClient() as client:
        # ── 1. Commit history ─────────────────────────────────────────
        yield {"type": "step", "message": f"Fetching commit history for `{file_path}`…"}
        commits_data = await _gh_get(
            client, f"/repos/{owner}/{repo_name}/commits",
            path=file_path, per_page=max_commits,   # 'path' here is a GitHub query param, not the function arg
        )
        if not commits_data:
            yield {"type": "error", "message": "File not found or repo is private / doesn't exist."}
            return

        yield {"type": "step", "message": f"Found {len(commits_data)} commits. Fetching linked PRs and issues…"}

        for c in commits_data:
            sha   = c["sha"]
            short = sha[:7]
            msg   = c["commit"]["message"].split("\n")[0]
            author_login = (c.get("author") or {}).get("login", c["commit"]["author"]["name"])
            date  = c["commit"]["author"]["date"][:10]

            commit_id = f"commit:{short}"
            nodes[commit_id] = _node(
                commit_id, "Commit", short,
                sha=sha, message=msg, author=author_login, date=date,
            )
            edges.append(_edge(file_id, commit_id, "MODIFIED_IN"))
            ai_items.append({"id": commit_id, "type": "Commit", "raw": f"Commit {short} by {author_login}: {msg}"})

            # Developer node
            dev_id = f"dev:{author_login}"
            if author_login not in seen_devs:
                seen_devs.add(author_login)
                avatar = (c.get("author") or {}).get("avatar_url", "")
                nodes[dev_id] = _node(dev_id, "Developer", author_login, avatar_url=avatar)
            edges.append(_edge(commit_id, dev_id, "AUTHORED_BY"))

            # ── 2. PRs linked to this commit ──────────────────────────
            try:
                prs = await _gh_get(
                    client, f"/repos/{owner}/{repo_name}/commits/{sha}/pulls",
                ) or []
            except Exception:
                prs = []

            # Also parse PR numbers from commit message
            msg_full = c["commit"]["message"]
            inline_pr_nums = [int(n) for n in _NUM_RE.findall(msg_full) if int(n) < 100000]

            all_pr_nums = {pr["number"] for pr in prs} | set(inline_pr_nums)

            for pr_data in prs:
                pr_num = pr_data["number"]
                if pr_num in seen_prs:
                    continue
                seen_prs.add(pr_num)

                pr_id = f"pr:{pr_num}"
                nodes[pr_id] = _node(
                    pr_id, "PullRequest", f"PR #{pr_num}",
                    number=pr_num,
                    title=pr_data.get("title", ""),
                    url=pr_data.get("html_url", ""),
                    state=pr_data.get("state", ""),
                    user=(pr_data.get("user") or {}).get("login", ""),
                )
                edges.append(_edge(commit_id, pr_id, "PART_OF"))
                pr_opener = (pr_data.get("user") or {}).get("login", "")
                if pr_opener:
                    dev_node_id = f"dev:{pr_opener}"
                    if pr_opener not in seen_devs:
                        seen_devs.add(pr_opener)
                        nodes[dev_node_id] = _node(dev_node_id, "Developer", pr_opener)
                    edges.append(_edge(dev_node_id, pr_id, "OPENED"))

                ai_items.append({
                    "id": pr_id, "type": "PullRequest",
                    "raw": f"PR #{pr_num}: {pr_data.get('title','')}. {(pr_data.get('body') or '')[:400]}",
                })

                # ── 3. Issues linked from PR body ────────────────────
                pr_body = pr_data.get("body") or ""
                issue_nums = [int(n) for n in _ISSUE_RE.findall(pr_body)]
                # also bare #N refs
                issue_nums += [int(n) for n in _NUM_RE.findall(pr_body) if int(n) < 100000]
                issue_nums = list(set(issue_nums))

                for issue_num in issue_nums[:4]:
                    if issue_num in seen_issues or issue_num == pr_num:
                        continue
                    seen_issues.add(issue_num)

                    try:
                        issue_data = await _gh_get(
                            client, f"/repos/{owner}/{repo_name}/issues/{issue_num}"
                        )
                    except Exception:
                        issue_data = None

                    if not issue_data or "pull_request" in issue_data:
                        continue

                    issue_id = f"issue:{issue_num}"
                    nodes[issue_id] = _node(
                        issue_id, "Issue", f"#{issue_num}",
                        number=issue_num,
                        title=issue_data.get("title", ""),
                        url=issue_data.get("html_url", ""),
                        state=issue_data.get("state", ""),
                    )
                    rel = "CLOSES" if re.search(
                        rf"(?:closes?|fixes?|resolves?)\s*#{issue_num}", pr_body, re.I
                    ) else "REFERENCES"
                    edges.append(_edge(pr_id, issue_id, rel))
                    ai_items.append({
                        "id": issue_id, "type": "Issue",
                        "raw": f"Issue #{issue_num}: {issue_data.get('title','')}. {(issue_data.get('body') or '')[:400]}",
                    })

    # ── 4. AI "why" summaries (per-node) ─────────────────────────────
    yield {"type": "step", "message": f"Generating per-node reasoning for {len(ai_items)} artifacts…"}
    why_map = await _ai_why(ai_items[:30])
    for node_id, why in why_map.items():
        if node_id in nodes:
            nodes[node_id]["why"] = why

    # ── 5. AI evolution narrative (holistic) ──────────────────────────
    yield {"type": "step", "message": "Writing AI evolution narrative for the full file history…"}
    narrative = await _ai_narrative(
        repo=f"{owner}/{repo_name}",
        file_path=file_path,
        ai_items=ai_items[:30],
    )
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
