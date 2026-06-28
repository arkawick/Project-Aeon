from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Optional
import json
import uuid
from datetime import datetime

from agents.orchestrator import analyze, analyze_stream, research_stream, postmortem
from agents.action_executor import execute_actions
from core.instances import chroma, neo4j

router = APIRouter(prefix="/ai", tags=["ai"])


class AnalyzeRequest(BaseModel):
    query: str
    context: dict = {}
    store_result: bool = True

    # Action execution (Days 13-14)
    auto_execute: bool = False   # if True, immediately execute actions after analysis
    repo: str = ""               # GitHub repo for issue/PR creation
    branch: str = ""             # fix branch (auto-derived if empty)
    job_name: str = ""           # Jenkins job for rebuild trigger
    n8n_workflow_id: str = ""    # n8n workflow to notify


@router.post("/analyze")
async def analyze_endpoint(body: AnalyzeRequest) -> dict[str, Any]:
    result = await analyze(body.query, body.context)

    # Store analysis in memory (memory_writer_node in graph already does this,
    # but this path is kept as a safety net for direct /analyze calls)
    incident_id = result.get("incident_id", f"ai_{uuid.uuid4().hex[:8]}")
    if body.store_result and result.get("root_cause") and "incident_id" not in result:
        now = datetime.utcnow().isoformat() + "Z"
        fix = result.get("suggested_fix", "")
        error_type = body.context.get("error_type", "ai_analysis")
        pipeline_id = body.context.get("pipeline_id", "unknown")

        await chroma.store_incident(
            incident_id=incident_id,
            description=body.query,
            logs=body.context.get("logs", ""),
            root_cause=result.get("root_cause", ""),
            fix=fix,
            extra_metadata={
                "title": body.query[:80],
                "severity": "medium",
                "status": "analyzed",
                "pipeline_id": pipeline_id,
                "error_type": error_type,
                "confidence": result.get("confidence", 0),
                "created_at": now,
                "resolved_at": "",
                "suggested_fix": fix,
            },
        )
        await neo4j.store_incident(
            incident_id=incident_id,
            pipeline_id=pipeline_id,
            error_type=error_type,
            fix_description=fix,
            severity="medium",
        )
        result["incident_id"] = incident_id

    # Auto-execute actions if requested
    if body.auto_execute:
        actions_result = await execute_actions(
            analysis=result,
            incident_id=incident_id,
            repo=body.repo,
            branch=body.branch,
            job_name=body.job_name,
            n8n_workflow_id=body.n8n_workflow_id,
            query=body.query,
        )
        result["actions"] = actions_result

    return result


@router.get("/stream")
async def stream_analysis(
    query: str = "Why did the latest build fail?",
    repo: str = "",
    auto_execute: bool = False,
):
    """
    SSE endpoint streaming LangGraph node events in real-time.

    When auto_execute=true, also streams action execution events after
    the analysis completes (issue creation, PR proposal).

    Event format: data: {"type": "...", "message": "...", ...}
    Final event:  data: {"type": "result", "content": {...}}
    Actions:      data: {"type": "actions", "content": {...}}
    Terminal:     data: [DONE]
    """
    async def event_generator():
        yield f"data: {json.dumps({'type': 'start', 'message': f'Analyzing: {query}'})}\n\n"

        final_result: dict = {}
        try:
            async for event in analyze_stream(query, {}):
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "result":
                    final_result = event.get("content", {})
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        # Execute actions after analysis if requested
        if auto_execute and final_result and repo:
            incident_id = final_result.get("incident_id", f"ai_{uuid.uuid4().hex[:8]}")
            yield f"data: {json.dumps({'type': 'actions_start', 'message': 'Executing actions...'})}\n\n"
            actions_result = await execute_actions(
                analysis=final_result,
                incident_id=incident_id,
                repo=repo,
                query=query,
            )
            yield f"data: {json.dumps({'type': 'actions', 'content': actions_result})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/research/stream")
async def research_stream_endpoint(query: str = "Investigate this incident deeply."):
    """SSE endpoint for deep research mode — more iterations, richer report output."""
    async def event_generator():
        yield f"data: {json.dumps({'type': 'start', 'message': f'Deep research: {query}'})}\n\n"
        try:
            async for event in research_stream(query, {}):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class PostmortemRequest(BaseModel):
    analysis: dict
    query: str = ""


@router.post("/postmortem")
async def generate_postmortem(body: PostmortemRequest) -> dict[str, Any]:
    """Generate a markdown post-mortem document from an analysis result."""
    doc = await postmortem(body.analysis, body.query)
    return {"markdown": doc}
