from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import json
import asyncio

from services.predict_service import predict_build

router = APIRouter(prefix="/predict", tags=["predict"])


@router.get("/stream")
async def predict_stream(
    repo:    str = Query(...),
    pr:      int = Query(..., ge=1),
    commits: int = Query(60, ge=10, le=200),
):
    """SSE stream — progress steps, a signals event, then the final verdict."""
    async def generate():
        try:
            async for event in predict_build(repo, pr, max_commits=commits):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
