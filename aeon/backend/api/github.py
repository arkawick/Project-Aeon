from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import os

from core.instances import github as github_svc

router = APIRouter(prefix="/github", tags=["github"])

MOCK_REPOS = [
    {"id": "repo_001", "name": "backend-api", "full_name": "acme/backend-api", "language": "Python", "stars": 42, "default_branch": "main"},
    {"id": "repo_002", "name": "frontend-app", "full_name": "acme/frontend-app", "language": "TypeScript", "stars": 18, "default_branch": "main"},
]

MOCK_RUNS = [
    {"id": "run_001", "name": "CI Pipeline", "status": "completed", "conclusion": "success", "branch": "main", "created_at": "2026-06-23T10:00:00Z"},
    {"id": "run_002", "name": "CI Pipeline", "status": "completed", "conclusion": "failure", "branch": "feature/new-ui", "created_at": "2026-06-23T09:45:00Z"},
    {"id": "run_003", "name": "Deploy Staging", "status": "in_progress", "conclusion": None, "branch": "develop", "created_at": "2026-06-23T10:20:00Z"},
]

MOCK_LOG_TEXT = """
Run ID: run_002 | Repo: acme/frontend-app | Branch: feature/new-ui

Step 1: Setup Node.js          ✓ (2s)
Step 2: Install dependencies   ✓ (28s)
Step 3: Build                  ✗ (18s)

--- Build Error ---
> frontend-app@0.1.0 build
> vite build

[vite] ERROR: Failed to resolve import "@/components/Button" from "src/App.tsx".
Does the file exist?
Build failed in 18.42s.
"""


def _has_token() -> bool:
    return bool(os.getenv("GITHUB_TOKEN", "").strip())


class IssueCreate(BaseModel):
    repo: str
    title: str
    body: str
    labels: list[str] = []


class PRCreate(BaseModel):
    repo: str
    title: str
    body: str
    branch: str
    base: str = "main"


@router.get("/repos")
async def list_repos() -> list[dict[str, Any]]:
    if not _has_token():
        return MOCK_REPOS
    result = await github_svc.get_repos()
    if result and "error" not in result[0]:
        return result
    return MOCK_REPOS


@router.get("/runs/{repo}")
async def get_workflow_runs(repo: str, limit: int = 10) -> list[dict[str, Any]]:
    if not _has_token():
        return [{**run, "repo": repo} for run in MOCK_RUNS]
    result = await github_svc.get_workflow_runs(repo, limit)
    if result and "error" not in result[0]:
        return result
    return [{**run, "repo": repo} for run in MOCK_RUNS]


@router.get("/logs/{repo}/{run_id}")
async def get_run_logs(repo: str, run_id: str) -> dict[str, Any]:
    if not _has_token():
        return {"repo": repo, "run_id": run_id, "logs": MOCK_LOG_TEXT, "source": "mock"}
    result = await github_svc.get_run_logs(repo, run_id)
    if "error" not in result:
        return {**result, "source": "github"}
    return {"repo": repo, "run_id": run_id, "logs": MOCK_LOG_TEXT, "source": "mock", "warning": result.get("error")}


@router.post("/issues")
async def create_issue(body: IssueCreate) -> dict[str, Any]:
    if not _has_token():
        return {
            "id": 9001, "number": 42, "title": body.title, "body": body.body,
            "repo": body.repo, "state": "open", "source": "mock",
            "url": f"https://github.com/{body.repo}/issues/42",
            "created_at": "2026-06-23T10:25:00Z",
        }
    result = await github_svc.create_issue(body.repo, body.title, body.body, body.labels)
    if "error" not in result:
        return {**result, "source": "github"}
    raise HTTPException(status_code=502, detail=f"GitHub API error: {result['error']}")


@router.post("/prs")
async def create_pr(body: PRCreate) -> dict[str, Any]:
    if not _has_token():
        return {
            "id": 8001, "number": 17, "title": body.title, "body": body.body,
            "repo": body.repo, "head": body.branch, "base": body.base,
            "state": "open", "source": "mock",
            "url": f"https://github.com/{body.repo}/pull/17",
            "created_at": "2026-06-23T10:25:00Z",
        }
    result = await github_svc.create_pr(body.repo, body.title, body.body, body.branch, body.base)
    if "error" not in result:
        return {**result, "source": "github"}
    raise HTTPException(status_code=502, detail=f"GitHub API error: {result['error']}")
