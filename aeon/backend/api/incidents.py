from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Any, Optional
import uuid
from datetime import datetime, timezone

from core.instances import chroma, neo4j
from agents.graph import _time_ago, _build_memory_match

router = APIRouter(prefix="/incidents", tags=["incidents"])

MOCK_INCIDENTS = [
    {
        "id": "inc_001",
        "title": "Build failure: missing module in frontend-app",
        "severity": "high",
        "status": "open",
        "root_cause": "Missing npm module '@/components/Button' due to incorrect import path alias configuration.",
        "suggested_fix": "Add resolve.alias to vite.config.js: '@': path.resolve(__dirname, 'src')",
        "pipeline_id": "pipe_002",
        "created_at": "2026-06-23T09:45:00Z",
        "resolved_at": None,
    },
    {
        "id": "inc_002",
        "title": "OOM in data-service integration tests",
        "severity": "critical",
        "status": "resolved",
        "root_cause": "Memory leak in database connection pool not releasing connections after test teardown.",
        "suggested_fix": "Call connection.close() in teardown fixtures or use a context manager.",
        "pipeline_id": "pipe_003",
        "created_at": "2026-06-22T14:00:00Z",
        "resolved_at": "2026-06-22T16:30:00Z",
    },
    {
        "id": "inc_003",
        "title": "Deployment timeout: backend-api to staging",
        "severity": "medium",
        "status": "open",
        "root_cause": "Health check endpoint taking >30s to respond due to cold-start DB connection initialization.",
        "suggested_fix": "Initialize DB connection pool eagerly at startup, not on first request.",
        "pipeline_id": "pipe_001",
        "created_at": "2026-06-23T07:20:00Z",
        "resolved_at": None,
    },
]


class IncidentCreate(BaseModel):
    title: str
    description: str
    logs: str = ""
    severity: str = "medium"
    pipeline_id: Optional[str] = None
    root_cause: str = ""
    suggested_fix: str = ""
    error_type: str = "unknown"


@router.get("/")
async def list_incidents() -> list[dict[str, Any]]:
    # Try ChromaDB first; fall back to mock
    chroma_items = await chroma.list_incidents(limit=50)
    if chroma_items:
        return [
            {
                "id": item["id"],
                **item["metadata"],
                "title": item["metadata"].get("title", item["id"]),
                "time_ago": _time_ago(item["metadata"].get("created_at", "")),
            }
            for item in chroma_items
        ]
    # Enrich mock data with time_ago
    return [
        {**inc, "time_ago": _time_ago(inc.get("created_at", ""))}
        for inc in MOCK_INCIDENTS
    ]


@router.get("/search")
async def search_incidents(
    q: str = Query(..., description="Natural language query"),
    top_k: int = Query(3, ge=1, le=10),
) -> list[dict[str, Any]]:
    """Semantic search over incident memory using ChromaDB."""
    results = await chroma.search_similar(q, top_k)
    if results:
        return [
            {
                "id": r["id"],
                "similarity": r["similarity"],
                **r["metadata"],
            }
            for r in results
        ]
    # Fallback: simple keyword match on mock data
    q_lower = q.lower()
    return [
        inc for inc in MOCK_INCIDENTS
        if q_lower in inc["title"].lower() or q_lower in inc["root_cause"].lower()
    ]


@router.get("/similar")
async def find_similar_incidents(
    q: str = Query(..., description="Log text, error message, or description"),
    top_k: int = Query(3, ge=1, le=10),
) -> dict[str, Any]:
    """
    Rich similarity search — returns memory_matches with relative timestamps,
    similarity scores, root causes and fixes. Used by the AI assistant cards.
    """
    hits = await chroma.search_similar(q, top_k)
    matches = [_build_memory_match(h) for h in hits]

    # Also query Neo4j for any strong error-type patterns
    words = [w for w in q.lower().split() if len(w) > 4]
    neo4j_patterns: list[dict] = []
    for kw in words[:2]:
        r = await neo4j.find_similar_errors(kw)
        if r.get("records"):
            neo4j_patterns.extend(r["records"])

    best = matches[0] if matches else None
    return {
        "query": q,
        "best_match": best,
        "matches": matches,
        "neo4j_patterns": neo4j_patterns[:5],
        "summary": (
            f"This matches incident {best['id']} from {best['time_ago']} "
            f"(similarity {int(best['similarity']*100)}%)."
            if best and best["similarity"] >= 0.75
            else "No strong match found in incident memory."
        ),
    }


@router.get("/graph/{error_type}")
async def get_error_graph(error_type: str) -> dict[str, Any]:
    """Query Neo4j for all incidents and fixes related to an error type."""
    history = await neo4j.get_error_fix_history(error_type)
    similar = await neo4j.find_similar_errors(error_type)
    return {
        "error_type": error_type,
        "history": history,
        "similar": similar,
    }


@router.get("/{incident_id}/graph")
async def get_incident_graph(incident_id: str) -> dict[str, Any]:
    """Return the Neo4j relationship graph for a specific incident."""
    return await neo4j.get_incident_graph(incident_id)


@router.get("/{incident_id}")
async def get_incident(incident_id: str) -> dict[str, Any]:
    item = await chroma.get_incident(incident_id)
    if item:
        return {"id": item["id"], **item["metadata"], "document": item["document"]}
    for incident in MOCK_INCIDENTS:
        if incident["id"] == incident_id:
            return incident
    return {
        "id": incident_id,
        "title": "Unknown incident",
        "severity": "low",
        "status": "unknown",
        "root_cause": "No data available.",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "resolved_at": None,
    }


@router.post("/", status_code=201)
async def create_incident(body: IncidentCreate) -> dict[str, Any]:
    incident_id = f"inc_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat() + "Z"
    pipeline_id = body.pipeline_id or "unknown"

    # Store in ChromaDB for semantic search
    await chroma.store_incident(
        incident_id=incident_id,
        description=body.description,
        logs=body.logs,
        root_cause=body.root_cause or body.description,
        fix=body.suggested_fix,
        extra_metadata={
            "title": body.title,
            "severity": body.severity,
            "status": "open",
            "pipeline_id": pipeline_id,
            "error_type": body.error_type,
            "created_at": now,
            "resolved_at": "",
            "suggested_fix": body.suggested_fix,
        },
    )

    # Store in Neo4j for relationship graph
    await neo4j.store_incident(
        incident_id=incident_id,
        pipeline_id=pipeline_id,
        error_type=body.error_type,
        fix_description=body.suggested_fix or body.description,
        severity=body.severity,
    )

    return {
        "id": incident_id,
        "title": body.title,
        "severity": body.severity,
        "status": "open",
        "root_cause": body.root_cause or body.description,
        "suggested_fix": body.suggested_fix,
        "pipeline_id": pipeline_id,
        "error_type": body.error_type,
        "created_at": now,
        "resolved_at": None,
        "stored_in": {"chromadb": True, "neo4j": True},
    }
