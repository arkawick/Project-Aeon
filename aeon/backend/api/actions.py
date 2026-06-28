"""
/api/actions — action execution and approval endpoints.

Flow:
  POST /execute   → runs immediate actions (issue, n8n) + queues PR proposal
  GET  /pending   → list all pending approvals
  POST /{id}/approve → approve a pending PR → creates PR → triggers rebuild
  POST /{id}/reject  → reject a pending action
  POST /trigger-rebuild → standalone Jenkins trigger (for manual use)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from agents.action_executor import (
    execute_actions,
    approve_action,
    reject_action,
    PENDING_ACTIONS,
    PR_CONFIDENCE_THRESHOLD,
)
from core.instances import jenkins as jenkins_svc

router = APIRouter(prefix="/actions", tags=["actions"])


class ExecuteRequest(BaseModel):
    # Analysis result from POST /api/ai/analyze
    analysis: dict
    incident_id: str

    # Context for action targeting
    repo: str = ""              # GitHub repo name, e.g. "frontend-app"
    branch: str = ""            # Fix branch name (auto-derived if empty)
    job_name: str = ""          # Jenkins job to rebuild after PR approval
    n8n_workflow_id: str = ""   # n8n workflow to notify
    query: str = ""             # Original user query (included in notifications)


class RejectRequest(BaseModel):
    reason: str = ""


class RebuildRequest(BaseModel):
    job_name: str
    params: dict = {}


@router.post("/execute")
async def execute(body: ExecuteRequest) -> dict[str, Any]:
    """
    Execute actions based on analysis result.

    Immediate (no approval needed):
      - Create GitHub issue with full root-cause context
      - Trigger n8n notification workflow

    Pending (requires approval):
      - Propose GitHub PR if confidence >= 85%

    Returns executed actions, pending actions, and skipped actions.
    """
    return await execute_actions(
        analysis=body.analysis,
        incident_id=body.incident_id,
        repo=body.repo,
        branch=body.branch,
        job_name=body.job_name,
        n8n_workflow_id=body.n8n_workflow_id,
        query=body.query,
    )


@router.get("/pending")
async def list_pending() -> dict[str, Any]:
    """List all pending actions awaiting human approval."""
    pending = [
        a for a in PENDING_ACTIONS.values()
        if a["status"] == "pending_approval"
    ]
    return {
        "count": len(pending),
        "actions": pending,
        "note": f"PR proposals require confidence >= {PR_CONFIDENCE_THRESHOLD}% and human approval.",
    }


@router.get("/all")
async def list_all_actions() -> dict[str, Any]:
    """List all actions regardless of status (for audit/debug)."""
    by_status: dict[str, list] = {}
    for a in PENDING_ACTIONS.values():
        by_status.setdefault(a["status"], []).append(a)
    return {"total": len(PENDING_ACTIONS), "by_status": by_status}


@router.post("/{action_id}/approve")
async def approve(action_id: str) -> dict[str, Any]:
    """
    Approve a pending action.

    For PR proposals:
      1. Creates the GitHub PR
      2. Triggers Jenkins rebuild (if job_name was provided)

    This is the human-in-the-loop step — Aeon never merges without approval.
    """
    result = await approve_action(action_id)
    if "error" in result and "No pending action" in result["error"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{action_id}/reject")
async def reject(action_id: str, body: RejectRequest = RejectRequest()) -> dict[str, Any]:
    """Reject a pending action."""
    result = await reject_action(action_id, body.reason)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/{action_id}")
async def get_action(action_id: str) -> dict[str, Any]:
    """Get the current state of a specific action."""
    action = PENDING_ACTIONS.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return action


@router.post("/trigger-rebuild")
async def trigger_rebuild(body: RebuildRequest) -> dict[str, Any]:
    """
    Standalone Jenkins rebuild trigger.
    Use this after manually applying a fix and wanting to verify the build passes.
    """
    result = await jenkins_svc.trigger_build(body.job_name, body.params)
    return {
        "job_name": body.job_name,
        "triggered": result.get("triggered", False),
        "details": result,
    }
