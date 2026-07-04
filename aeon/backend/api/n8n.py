from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any
import os

from core.instances import n8n as n8n_svc

router = APIRouter(prefix="/n8n", tags=["n8n"])

# These webhook IDs match the n8n workflow JSONs in aeon/n8n/workflows/
# After importing those workflows, n8n will route POST /webhook/{id} to each flow.
MOCK_WORKFLOWS = [
    {
        "id": "aeon-ci-failure",
        "name": "Notify Slack on CI Failure",
        "active": True,
        "trigger": "webhook",
        "webhook_path": "aeon-ci-failure",
        "last_run": "2026-06-23T09:46:00Z",
        "description": "Receives CI failure events from Aeon and sends a formatted Slack notification",
        "source": "n8n",
    },
    {
        "id": "aeon-incident",
        "name": "Auto-create GitHub Issue on Incident",
        "active": True,
        "trigger": "webhook",
        "webhook_path": "aeon-incident",
        "last_run": "2026-06-22T15:00:00Z",
        "description": "Creates a GitHub issue automatically when Aeon detects a new incident",
        "source": "n8n",
    },
]


class TriggerPayload(BaseModel):
    payload: dict = {}


@router.get("/workflows")
async def list_workflows() -> list[dict[str, Any]]:
    # Try live n8n API first; fall back to mock (which has the right webhook IDs)
    if os.getenv("N8N_API_KEY", "").strip():
        result = await n8n_svc.list_workflows()
        # The service signals failure with [{"error": ...}] — check the KEY, not a
        # substring of the JSON (real workflows contain "onError" in node settings).
        if result and "error" not in result[0]:
            return result
    return MOCK_WORKFLOWS


@router.post("/workflows/{workflow_id}/trigger")
async def trigger_workflow(workflow_id: str, body: TriggerPayload = TriggerPayload()) -> dict[str, Any]:
    result = await n8n_svc.trigger_workflow(workflow_id, body.payload)
    return {**result, "source": "n8n"}
