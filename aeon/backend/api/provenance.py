from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import asyncio
from typing import Any

from services.provenance_service import build_provenance_graph, fetch_commit_diff
from core.instances import neo4j

router = APIRouter(prefix="/provenance", tags=["provenance"])


class ProvenanceRequest(BaseModel):
    repo: str
    file_path: str
    max_commits: int = 12


@router.get("/stream")
async def provenance_stream(
    repo: str = Query(...),
    file_path: str = Query(...),
    max_commits: int = Query(12, ge=1, le=30),
):
    """
    SSE stream. Emits progress steps then the final graph result.
    Frontend connects with EventSource and receives JSON-encoded events.
    """
    async def generate():
        try:
            async for event in build_provenance_graph(repo, file_path, max_commits):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)   # flush
                if event["type"] == "result":
                    # Cache the graph in Neo4j
                    asyncio.create_task(_cache(repo, file_path, event))
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/cached")
async def get_cached_graph(
    repo: str = Query(...),
    file_path: str = Query(...),
) -> dict[str, Any]:
    """Return a previously cached provenance graph from Neo4j (if available)."""
    graph = await neo4j.get_provenance_graph(repo, file_path)
    return graph


@router.get("/diff")
async def get_commit_diff(
    repo: str = Query(...),
    sha:  str = Query(...),
) -> dict[str, Any]:
    """Return the actual code diff for a commit (files changed + patch lines)."""
    return await fetch_commit_diff(repo, sha)


async def _cache(repo: str, file_path: str, event: dict):
    """Fire-and-forget: persist graph nodes/edges to Neo4j."""
    try:
        await neo4j.store_provenance_graph(repo, file_path, event["nodes"], event["edges"])
    except Exception as exc:
        print(f"[provenance] Neo4j cache error: {exc}")
