"""
Blast Radius Analyzer
=====================
Given a GitHub PR, maps which files changed → which services, tests, configs,
and pipelines are impacted → AI risk assessment with deploy recommendation.

Graph schema:
  (PR)-[:CHANGED]->(File)-[:IMPACTS]->(Service|Test|Config|Pipeline|Infrastructure|Dependencies)
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
from typing import Any, AsyncIterator

import anthropic
import httpx

GH_API = "https://api.github.com"

# Robustness limits
MAX_FILE_PAGES = 5    # paginate up to 500 changed files on large PRs
MAX_GRAPH_FILES = 40  # cap graph nodes for readability (counts still cover all files)
GH_RETRIES = 3        # retries on transient network / 5xx errors

NODE_COLORS = {
    "PR":             "#22c55e",
    "File":           "#64748b",
    "Service":        "#f97316",
    "Test":           "#a855f7",
    "Config":         "#eab308",
    "Pipeline":       "#3b82f6",
    "Infrastructure": "#ec4899",
    "Dependencies":   "#ef4444",
    "Docs":           "#94a3b8",
    "Incident":       "#9cdef2",
}

RISK_COLOR = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#22c55e", "UNKNOWN": "#64748b"}


def _gh_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _gh_get(client: httpx.AsyncClient, endpoint: str, **params) -> Any:
    """GET a GitHub endpoint with retry + backoff on transient failures.

    Retries network errors and 5xx responses; never retries 403/429 (rate
    limit) or 404 (not found), which are surfaced immediately.
    """
    url = f"{GH_API}{endpoint}"
    last_error = "unknown error"

    for attempt in range(GH_RETRIES):
        try:
            resp = await client.get(url, headers=_gh_headers(), params=params, timeout=20.0)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"network error: {exc}"
            await asyncio.sleep(0.5 * (2 ** attempt))
            continue

        if resp.status_code == 404:
            return None
        if resp.status_code in (403, 429):
            has_token = bool(os.getenv("GITHUB_TOKEN", "").strip())
            reset_ts = resp.headers.get("X-RateLimit-Reset", "")
            reset_str = ""
            if reset_ts:
                import datetime
                try:
                    reset_str = f" Resets at {datetime.datetime.utcfromtimestamp(int(reset_ts)).strftime('%H:%M UTC')}."
                except Exception:
                    pass
            if not has_token:
                raise RuntimeError(
                    "GitHub rate limit — add GITHUB_TOKEN to aeon/backend/.env and run: docker compose up -d backend." + reset_str
                )
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after:
                raise RuntimeError(f"GitHub secondary rate limit. Wait {retry_after}s before retrying." + reset_str)
            raise RuntimeError(f"GitHub rate limit exhausted (authenticated).{reset_str}")
        if resp.status_code >= 500:
            last_error = f"GitHub {resp.status_code} server error"
            await asyncio.sleep(0.5 * (2 ** attempt))
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError(f"GitHub request failed after {GH_RETRIES} attempts ({last_error}).")


def _classify_file(filepath: str) -> tuple[str, str]:
    """Returns (category, risk_level)."""
    fp = filepath.lower()
    parts = fp.split("/")
    filename = parts[-1]

    # Dependency manifests — HIGH
    dep_names = {
        "package.json", "requirements.txt", "go.mod", "go.sum",
        "gemfile", "gemfile.lock", "pom.xml", "build.gradle",
        "cargo.toml", "cargo.lock", "pyproject.toml", "setup.py",
        "setup.cfg", "composer.json",
    }
    if filename in dep_names or filename.endswith((".lock", "-lock.json")):
        return ("Dependencies", "HIGH")

    # Infrastructure — HIGH
    if "dockerfile" in filename or "docker-compose" in filename or filename == ".dockerignore":
        return ("Infrastructure", "HIGH")
    if any(p in parts for p in ("k8s", "kubernetes", "helm", "terraform", "infra", "deploy")):
        return ("Infrastructure", "HIGH")

    # CI / Pipeline — MEDIUM
    if ".github/workflows" in filepath or "jenkinsfile" in filename or ".circleci" in filepath:
        return ("Pipeline", "MEDIUM")
    if any(p in parts for p in ("ci", ".travis")) and filename.endswith((".yml", ".yaml")):
        return ("Pipeline", "MEDIUM")

    # Config — HIGH
    if filename in ("config.py", "settings.py", "configuration.js", "config.ts") or \
       filename.endswith((".env", ".env.example", ".env.sample")):
        return ("Config", "HIGH")
    if filename.endswith((".yml", ".yaml", ".toml", ".ini", ".cfg")) and \
       not any(p in parts for p in ("test", "tests", "__tests__", "spec")):
        return ("Config", "MEDIUM")

    # Tests — LOW
    test_dirs = {"test", "tests", "__tests__", "spec", "specs", "testing", "e2e"}
    if any(p in test_dirs for p in parts):
        return ("Test", "LOW")
    test_suffixes = ("_test.py", ".test.js", ".spec.js", ".test.ts", ".spec.ts", "_test.go", "test_.py")
    if filename.endswith(test_suffixes):
        return ("Test", "LOW")

    # Docs — LOW
    if filename.endswith((".md", ".rst", ".txt")) or "docs" in parts or "documentation" in parts:
        return ("Docs", "LOW")

    # Everything else is Service code — HIGH
    return ("Service", "HIGH")


def _infer_service(filepath: str) -> str:
    """Infer a human-readable service/module name from the file path."""
    parts = filepath.split("/")
    top = parts[0].lower()

    # Monorepo: packages/auth/src/... → auth
    if top in ("packages", "services", "apps", "modules", "libs") and len(parts) > 1:
        return parts[1]

    # Standard layout: src/middleware/logger.js → middleware
    if top in ("src", "lib", "app", "api", "backend", "frontend") and len(parts) > 2:
        return parts[1]

    # Fallback: top directory or filename stem
    if len(parts) > 1:
        return parts[0]
    return parts[-1].rsplit(".", 1)[0]


def _node(nid: str, ntype: str, label: str, **extra) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "label": label, "color": NODE_COLORS.get(ntype, "#64748b"), **extra}


def _edge(source: str, target: str, rel: str) -> dict[str, Any]:
    return {"source": source, "target": target, "type": rel}


async def _search_incident_memory(
    pr_title: str,
    changed_files: list[tuple],
    services: set[str],
) -> list[dict[str, Any]]:
    """
    Query Aeon's ChromaDB incident memory for past incidents related to this PR.
    A match survives if a changed filename literally appears in the incident
    document, or if the semantic similarity is high enough on its own.
    """
    try:
        from core.instances import chroma
    except Exception:
        return []

    basenames = [fp.split("/")[-1] for fp, *_ in changed_files]
    query = (
        f"{pr_title}\n"
        f"Changed files: {', '.join(basenames[:20])}\n"
        f"Services: {', '.join(sorted(services)) or 'n/a'}"
    )
    hits = await chroma.search_similar(query, top_k=5)

    matches: list[dict[str, Any]] = []
    for h in hits:
        doc = (h.get("document") or "").lower()
        meta = h.get("metadata") or {}
        similarity = h.get("similarity", 0)
        matched = sorted({bn for bn in basenames if len(bn) > 3 and bn.lower() in doc})
        if not matched and similarity < 0.35:
            continue
        matches.append({
            "incident_id":   meta.get("incident_id", h.get("id", "")),
            "similarity":    similarity,
            "matched_files": matched[:6],
            "root_cause":    (meta.get("root_cause") or "")[:300],
            "fix":           (meta.get("fix") or "")[:300],
        })
    return matches


async def _ai_risk(
    repo: str,
    pr_title: str,
    pr_body: str,
    changed_files: list[tuple],
    impact_counts: dict[str, int],
    memory_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from core import llm

    if not llm.llm_available():
        return {"risk_level": "UNKNOWN", "narrative": "Add AZURE_OPENAI_API_KEY or ANTHROPIC_API_KEY to .env for AI risk assessment.", "deploy_recommendation": "", "must_test": []}

    file_lines = "\n".join(
        f"  [{cat}/{risk}] {fp}  +{add}/-{rem}"
        for fp, cat, risk, add, rem in changed_files[:20]
    )
    impact_str = ", ".join(f"{k}: {v}" for k, v in impact_counts.items())

    memory_str = "None found."
    if memory_matches:
        memory_str = "\n".join(
            f"  - Incident {m['incident_id']} (similarity {m['similarity']:.0%}"
            + (f", mentions changed files: {', '.join(m['matched_files'])}" if m["matched_files"] else "")
            + f") — root cause: {m['root_cause'] or 'n/a'}; fix: {m['fix'] or 'n/a'}"
            for m in memory_matches
        )

    prompt = f"""You are a senior DevOps engineer reviewing a pull request for production deployment risk.

Repository: {repo}
PR Title: {pr_title}
PR Description: {(pr_body or "")[:500]}

Changed files:
{file_lines}

Impact summary: {impact_str}

Related past incidents from Aeon's incident memory (vector search over previous CI/CD failures):
{memory_str}

If a past incident is relevant, reference it explicitly in the narrative (e.g. "this matches incident #421")
and factor it into the risk level and must_test items.

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{{
  "risk_level": "HIGH" or "MEDIUM" or "LOW",
  "narrative": "2-3 sentences: what is risky and why",
  "deploy_recommendation": "one clear sentence: safe / deploy with caution / do not deploy",
  "must_test": ["specific thing to verify", "another thing"]
}}

Be specific — reference actual filenames and inferred service names."""

    text = await llm.complete(system="", user=prompt, max_tokens=500)
    if text is None:
        return {"risk_level": "UNKNOWN", "narrative": "AI risk assessment unavailable (no LLM provider responded).", "deploy_recommendation": "", "must_test": []}
    text = text.strip()
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return _json.loads(m.group())
    except Exception:
        pass
    return {"risk_level": "MEDIUM", "narrative": text or "No assessment returned.", "deploy_recommendation": "", "must_test": []}


async def build_blast_radius(repo: str, pr_number: int) -> AsyncIterator[dict[str, Any]]:
    owner_repo = repo.strip("/").replace("https://github.com/", "")
    parts = owner_repo.split("/")
    if len(parts) < 2:
        yield {"type": "error", "message": f"Invalid repo '{repo}'. Use owner/repo format."}
        return

    owner, repo_name = parts[0], parts[1]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    async with httpx.AsyncClient() as client:
        # ── PR metadata ───────────────────────────────────────────────
        yield {"type": "step", "message": f"Fetching PR #{pr_number} from {owner}/{repo_name}…"}
        pr = await _gh_get(client, f"/repos/{owner}/{repo_name}/pulls/{pr_number}")
        if not pr:
            # Check if this number exists as an issue (common mistake)
            issue = await _gh_get(client, f"/repos/{owner}/{repo_name}/issues/{pr_number}")
            if issue and "pull_request" not in issue:
                yield {"type": "error", "message": f"#{pr_number} is an Issue, not a Pull Request. Go to github.com/{owner}/{repo_name}/pulls and pick a PR number."}
            elif issue and "pull_request" in issue:
                yield {"type": "error", "message": f"#{pr_number} exists but the GitHub API returned no data. It may be a draft or very old PR. Try another PR number."}
            else:
                yield {"type": "error", "message": f"PR #{pr_number} not found in {owner}/{repo_name}. Check the number in the repo's Pull Requests tab."}
            return

        pr_id = f"pr:{pr_number}"
        nodes[pr_id] = _node(
            pr_id, "PR", f"PR #{pr_number}",
            title=pr.get("title", ""),
            url=pr.get("html_url", ""),
            state=pr.get("state", "open"),
            author=(pr.get("user") or {}).get("login", ""),
            additions=pr.get("additions", 0),
            deletions=pr.get("deletions", 0),
            changed_files=pr.get("changed_files", 0),
            base_branch=pr.get("base", {}).get("ref", ""),
            head_branch=pr.get("head", {}).get("ref", ""),
        )

        # ── Changed files ─────────────────────────────────────────────
        total = pr.get("changed_files", "?")
        yield {"type": "step", "message": f"Analyzing {total} changed files…"}
        files_data: list[dict] = []
        for page in range(1, MAX_FILE_PAGES + 1):
            batch = await _gh_get(
                client, f"/repos/{owner}/{repo_name}/pulls/{pr_number}/files",
                per_page=100, page=page,
            )
            if not batch:
                break
            files_data.extend(batch)
            if len(batch) < 100:  # last page reached
                break
        if not files_data:
            yield {"type": "error", "message": "Could not fetch PR files."}
            return

    # ── Build graph ───────────────────────────────────────────────────
    yield {"type": "step", "message": "Mapping impact across services, tests, and infrastructure…"}

    changed_files: list[tuple] = []
    impact_counts: dict[str, int] = {}
    seen_impacts: set[str] = set()

    for idx, f in enumerate(files_data):
        fp        = f.get("filename", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        status    = f.get("status", "modified")

        category, risk = _classify_file(fp)
        changed_files.append((fp, category, risk, additions, deletions))
        impact_counts[category] = impact_counts.get(category, 0) + 1

        # Count every file above, but cap graph nodes for readability
        if idx >= MAX_GRAPH_FILES:
            continue

        # File node
        file_id = f"file:{fp}"
        nodes[file_id] = _node(
            file_id, "File", fp.split("/")[-1],
            full_path=fp,
            category=category,
            risk=risk,
            additions=additions,
            deletions=deletions,
            status=status,
        )
        edges.append(_edge(pr_id, file_id, "CHANGED"))

        # Impact node
        if category == "Service":
            svc = _infer_service(fp)
            impact_id = f"service:{svc}"
            if impact_id not in seen_impacts:
                seen_impacts.add(impact_id)
                nodes[impact_id] = _node(impact_id, "Service", svc, risk=risk, file_count=0)
            nodes[impact_id]["file_count"] = nodes[impact_id].get("file_count", 0) + 1
        else:
            impact_id = f"impact:{category}"
            if impact_id not in seen_impacts:
                seen_impacts.add(impact_id)
                nodes[impact_id] = _node(impact_id, category, category, risk=risk, file_count=0)
            nodes[impact_id]["file_count"] = nodes[impact_id].get("file_count", 0) + 1

        edges.append(_edge(file_id, impact_id, "IMPACTS"))

    # ── Incident memory recall ────────────────────────────────────────
    yield {"type": "step", "message": "Searching Aeon incident memory for related past incidents…"}
    services_touched = {n["label"] for n in nodes.values() if n["type"] == "Service"}
    memory_matches = await _search_incident_memory(pr.get("title", ""), changed_files, services_touched)
    if memory_matches:
        yield {"type": "step", "message": f"Found {len(memory_matches)} related past incident(s) in memory."}
        for m in memory_matches:
            inc_id = f"incident:{m['incident_id']}"
            nodes[inc_id] = _node(
                inc_id, "Incident", str(m["incident_id"]),
                similarity=m["similarity"],
                matched_files=m["matched_files"],
                root_cause=m["root_cause"],
                fix=m["fix"],
            )
            edges.append(_edge(pr_id, inc_id, "RECALLS"))
    else:
        yield {"type": "step", "message": "No related incidents found in memory."}
    yield {"type": "memory", "matches": memory_matches}

    # ── AI risk assessment ────────────────────────────────────────────
    yield {"type": "step", "message": "Generating AI risk assessment…"}
    risk_result = await _ai_risk(
        repo=f"{owner}/{repo_name}",
        pr_title=pr.get("title", ""),
        pr_body=pr.get("body", ""),
        changed_files=changed_files,
        impact_counts=impact_counts,
        memory_matches=memory_matches,
    )
    yield {"type": "risk", **risk_result}

    # ── Result ────────────────────────────────────────────────────────
    yield {
        "type":  "result",
        "nodes": list(nodes.values()),
        "edges": edges,
        "meta":  {
            "repo":         f"{owner}/{repo_name}",
            "pr":           pr_number,
            "pr_title":     pr.get("title", ""),
            "pr_url":       pr.get("html_url", ""),
            "author":       (pr.get("user") or {}).get("login", ""),
            "state":        pr.get("state", ""),
            "total_files":  pr.get("changed_files", 0),
            "additions":    pr.get("additions", 0),
            "deletions":    pr.get("deletions", 0),
            "impacts":      impact_counts,
            "risk_level":   risk_result.get("risk_level", "UNKNOWN"),
            "related_incidents": len(memory_matches),
        },
    }
