from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from typing import Any
import json
import asyncio

from services.blast_radius_service import build_blast_radius

router = APIRouter(prefix="/blast", tags=["blast-radius"])


@router.get("/stream")
async def blast_stream(
    repo:      str = Query(...),
    pr:        int = Query(..., ge=1),
):
    """SSE stream — progress steps, risk event, then final graph result."""
    async def generate():
        try:
            async for event in build_blast_radius(repo, pr):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
