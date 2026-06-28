from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any
import os

from core.instances import jenkins as jenkins_svc

router = APIRouter(prefix="/jenkins", tags=["jenkins"])

MOCK_BUILDS = [
    {"id": "build_001", "job": "backend-api", "number": 88, "status": "SUCCESS", "duration": 142000, "timestamp": "2026-06-23T09:00:00Z"},
    {"id": "build_002", "job": "frontend-app", "number": 55, "status": "FAILURE", "duration": 68000, "timestamp": "2026-06-23T09:45:00Z"},
    {"id": "build_003", "job": "data-service", "number": 31, "status": "ABORTED", "duration": 30000, "timestamp": "2026-06-23T10:10:00Z"},
]

MOCK_CONSOLE = """
Started by user admin
Building in workspace /var/jenkins_home/workspace/frontend-app
[frontend-app] $ npm ci
npm warn deprecated inflight@1.0.6: ...
added 1423 packages in 28s
[frontend-app] $ npm run build
> frontend-app@0.1.0 build
> vite build

Build failed: Cannot resolve module '@/components/Button'
Finished: FAILURE
"""


def _has_config() -> bool:
    return bool(os.getenv("JENKINS_TOKEN", "").strip())


class TriggerRequest(BaseModel):
    params: dict = {}


@router.get("/builds")
async def list_builds(job: str = "frontend-app", limit: int = 10) -> list[dict[str, Any]]:
    if not _has_config():
        return MOCK_BUILDS
    result = await jenkins_svc.get_builds(job, limit)
    if result and "error" not in result[0]:
        return result
    return MOCK_BUILDS


@router.get("/builds/{job_name}/{build_number}/logs")
async def get_build_logs(job_name: str, build_number: int) -> dict[str, Any]:
    if not _has_config():
        return {"job": job_name, "build_number": build_number, "console_output": MOCK_CONSOLE, "source": "mock"}
    result = await jenkins_svc.get_build_logs(job_name, build_number)
    if "error" not in result:
        return {**result, "console_output": result.get("logs", ""), "source": "jenkins"}
    return {"job": job_name, "build_number": build_number, "console_output": MOCK_CONSOLE, "source": "mock", "warning": result.get("error")}


@router.post("/builds/{job_name}/trigger")
async def trigger_build(job_name: str, body: TriggerRequest = TriggerRequest()) -> dict[str, Any]:
    if not _has_config():
        return {"triggered": True, "build_number": 99, "job": job_name, "source": "mock"}
    result = await jenkins_svc.trigger_build(job_name, body.params)
    return {**result, "source": "jenkins"}
