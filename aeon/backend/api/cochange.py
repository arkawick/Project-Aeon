from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import json
import asyncio

from services.cochange_service import build_cochange_graph

router = APIRouter(prefix="/cochange", tags=["cochange"])


@router.get("/stream")
async def cochange_stream(
    repo:      str = Query(...),
    commits:   int = Query(100, ge=10, le=300),
    file_path: str = Query(""),
):
    """SSE stream — progress steps, AI insight, then the coupling graph."""
    async def generate():
        try:
            async for event in build_cochange_graph(repo, commits, file_path):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
