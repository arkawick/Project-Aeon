from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Any, Optional
import os
import uuid
from datetime import datetime, timezone

from core.instances import github as github_svc, jenkins as jenkins_svc, chroma as chroma_store

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

# In-memory store for webhook-ingested pipeline events (survives between requests)
_INGESTED: list[dict] = []


class PipelineWebhookPayload(BaseModel):
    """Generic pipeline event accepted from Jenkins, GitHub Actions, or any CI system."""
    source: str                          # "jenkins" | "github" | "n8n" | etc.
    name: str                            # job / workflow name
    status: str                          # "success" | "failure" | "running"
    repo: Optional[str] = ""
    branch: Optional[str] = "main"
    duration: Optional[str] = ""
    build_number: Optional[int] = None
    run_id: Optional[str] = None
    url: Optional[str] = ""
    logs: Optional[str] = ""             # console output (stored in ChromaDB for AI search)
    error_summary: Optional[str] = ""   # one-line error extracted by CI step
    commit_sha: Optional[str] = ""
    triggered_by: Optional[str] = ""


@router.post("/ingest", status_code=201)
async def ingest_pipeline_event(body: PipelineWebhookPayload) -> dict[str, Any]:
    """
    Universal webhook receiver for CI/CD build events.

    Call this from:
      - Jenkins post{} block: curl -X POST http://<AEON_URL>/api/pipelines/ingest ...
      - GitHub Actions on-failure step: curl ...
      - Any other CI system

    On failure, the logs are stored in ChromaDB so the AI assistant
    can find them via semantic search.
    """
    pipeline_id = f"wh_{body.source}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "id": pipeline_id,
        "name": body.name,
        "status": body.status,
        "source": body.source,
        "repo": body.repo,
        "branch": body.branch,
        "duration": body.duration,
        "build_number": body.build_number,
        "run_id": body.run_id,
        "url": body.url,
        "error_summary": body.error_summary,
        "commit_sha": body.commit_sha,
        "triggered_by": body.triggered_by,
        "timestamp": now,
    }
    _INGESTED.append(record)
    # Keep last 100 events in memory
    if len(_INGESTED) > 100:
        _INGESTED.pop(0)

    # Store failed builds in ChromaDB so the AI can find them
    if body.status == "failure" and (body.logs or body.error_summary):
        description = f"{body.source} job '{body.name}' failed on branch {body.branch}"
        if body.repo:
            description += f" in {body.repo}"
        await chroma_store.store_incident(
            incident_id=pipeline_id,
            description=description,
            logs=body.logs or "",
            root_cause=body.error_summary or "Build failure — see logs",
            fix="",
            extra_metadata={
                "title": f"[{body.source.upper()}] {body.name} failed",
                "severity": "high",
                "status": "open",
                "pipeline_id": pipeline_id,
                "error_type": "build_failure",
                "source": body.source,
                "repo": body.repo or "",
                "branch": body.branch or "",
                "build_number": str(body.build_number or ""),
                "created_at": now,
                "resolved_at": "",
                "suggested_fix": "",
            },
        )

    return {"id": pipeline_id, "stored": True, "chroma_indexed": body.status == "failure"}

MOCK_PIPELINES = [
    {
        "id": "pipe_001",
        "name": "build-and-test",
        "status": "success",
        "source": "github",
        "repo": "acme/backend-api",
        "branch": "main",
        "duration": "3m 42s",
        "timestamp": "2026-06-23T10:15:00Z",
        "url": "https://github.com/acme/backend-api/actions",
    },
    {
        "id": "pipe_002",
        "name": "deploy-staging",
        "status": "failure",
        "source": "github",
        "repo": "acme/frontend-app",
        "branch": "feature/new-ui",
        "duration": "1m 08s",
        "timestamp": "2026-06-23T09:45:00Z",
        "url": "https://github.com/acme/frontend-app/actions",
    },
    {
        "id": "pipe_003",
        "name": "integration-tests",
        "status": "running",
        "source": "jenkins",
        "repo": "acme/data-service",
        "branch": "develop",
        "duration": "0m 55s",
        "timestamp": "2026-06-23T10:20:00Z",
        "url": "http://localhost:8080/job/integration-tests/",
    },
]

MOCK_LOGS = """
2026-06-23T09:45:01Z [INFO]  Starting pipeline: deploy-staging
2026-06-23T09:45:02Z [INFO]  Checking out branch: feature/new-ui
2026-06-23T09:45:10Z [INFO]  Installing dependencies...
2026-06-23T09:45:40Z [INFO]  Running build...
2026-06-23T09:45:58Z [ERROR] Build failed: Cannot find module '@/components/Button'
2026-06-23T09:46:05Z [ERROR] Module resolution failed. Check import paths.
2026-06-23T09:46:06Z [FATAL] Pipeline terminated with exit code 1
"""

_GH_CONCLUSION_MAP = {
    "success": "success",
    "failure": "failure",
    "cancelled": "failure",
    "timed_out": "failure",
    "skipped": "success",
    None: "running",
}


def _ms_to_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}m {s % 60}s"


async def _fetch_github_pipelines() -> list[dict[str, Any]]:
    if not os.getenv("GITHUB_TOKEN", "").strip():
        return []
    try:
        repos = await github_svc.get_repos()
        pipelines: list[dict[str, Any]] = []
        for repo in repos[:5]:
            if "error" in repo:
                continue
            repo_name = repo.get("name", "")
            full_name = repo.get("full_name", repo_name)
            if not repo_name:
                continue
            runs = await github_svc.get_workflow_runs(repo_name, limit=5)
            for run in runs:
                if "error" in run:
                    continue
                repo_info = run.get("repository") or {}
                pipelines.append({
                    "id": f"gh_{run.get('id', '')}",
                    "name": run.get("name", "GitHub Actions"),
                    "status": _GH_CONCLUSION_MAP.get(run.get("conclusion"), "running"),
                    "source": "github",
                    "repo": repo_info.get("full_name") or full_name,
                    "branch": run.get("head_branch", "main"),
                    "duration": _ms_to_duration(run.get("run_duration_ms") or 0),
                    "timestamp": run.get("created_at", ""),
                    "run_id": str(run.get("id", "")),
                    "url": run.get("html_url", ""),
                })
        return pipelines
    except Exception:
        return []


_JENKINS_COLOR_MAP = {
    "blue": "success",
    "blue_anime": "running",
    "red": "failure",
    "red_anime": "running",
    "yellow": "failure",
    "yellow_anime": "running",
    "grey": "unknown",
    "grey_anime": "running",
    "disabled": "unknown",
    "aborted": "failure",
    "aborted_anime": "running",
}


async def _fetch_jenkins_pipelines() -> list[dict[str, Any]]:
    jenkins_url = os.getenv("JENKINS_URL", "").strip()
    if not jenkins_url:
        return []
    try:
        jobs = await jenkins_svc.list_jobs()
        pipelines: list[dict[str, Any]] = []
        for job in jobs:
            if "error" in job:
                continue
            color = job.get("color", "grey")
            status = _JENKINS_COLOR_MAP.get(color, "unknown")
            last_build = job.get("lastBuild") or {}
            build_num = last_build.get("number", 0)
            ts_ms = last_build.get("timestamp", 0)
            timestamp = ""
            if ts_ms:
                from datetime import datetime, timezone
                timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            job_name = job.get("name", "")
            # Use localhost URL so the link opens in the user's browser (not Docker network)
            public_url = f"http://localhost:8080/job/{job_name}/{build_num}"
            pipelines.append({
                "id": f"jenkins_{job_name}_{build_num}",
                "name": job_name,
                "status": status,
                "source": "jenkins",
                "repo": job_name,
                "branch": "main",
                "duration": _ms_to_duration(last_build.get("duration", 0)),
                "timestamp": timestamp,
                "build_number": build_num,
                "url": public_url,
            })
        return pipelines
    except Exception:
        return []


@router.get("/")
async def list_pipelines() -> list[dict[str, Any]]:
    gh_pipes, jenkins_pipes = await _fetch_github_pipelines(), await _fetch_jenkins_pipelines()
    combined = gh_pipes + jenkins_pipes + list(reversed(_INGESTED))
    if not combined:
        return MOCK_PIPELINES
    # Fill in mock entries for any source that returned nothing (e.g. no token configured)
    if not gh_pipes:
        combined += [p for p in MOCK_PIPELINES if p["source"] == "github"]
    if not jenkins_pipes:
        combined += [p for p in MOCK_PIPELINES if p["source"] == "jenkins"]
    return sorted(combined, key=lambda p: p.get("timestamp", ""), reverse=True)


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    for pipeline in MOCK_PIPELINES:
        if pipeline["id"] == pipeline_id:
            return {**pipeline, "logs": MOCK_LOGS}
    return {
        "id": pipeline_id,
        "name": "unknown-pipeline",
        "status": "unknown",
        "source": "mock",
        "repo": "acme/unknown",
        "branch": "main",
        "duration": "0m 0s",
        "timestamp": "2026-06-23T00:00:00Z",
        "logs": "No logs available.",
    }
