"""
Memory management endpoints — status, seed, and graph insights.
Used to verify ChromaDB + Neo4j connectivity and pre-load demo data.
"""
from fastapi import APIRouter
from typing import Any

from core.instances import chroma, neo4j

router = APIRouter(prefix="/memory", tags=["memory"])

SEED_INCIDENTS = [
    {
        "id": "inc_seed_001",
        "description": "Frontend build failed due to unresolved import path alias '@/components'",
        "logs": "ERROR: Cannot find module '@/components/Button'\nvite build failed in 18s",
        "root_cause": "Vite path alias '@' not configured in vite.config.js resolve.alias",
        "fix": "Add resolve: { alias: { '@': path.resolve(__dirname, 'src') } } to vite.config.js",
        "error_type": "module_resolution_error",
        "pipeline_id": "pipe_frontend_42",
        "severity": "high",
    },
    {
        "id": "inc_seed_002",
        "description": "Integration tests OOM killed after running for 45 minutes",
        "logs": "FATAL ERROR: CALL_AND_RETRY_LAST Allocation failed - JavaScript heap out of memory\nKilled",
        "root_cause": "Memory leak in database connection pool — connections not released after test teardown",
        "fix": "Add afterEach hook to call pool.end() or use connection.release() in finally block",
        "error_type": "out_of_memory",
        "pipeline_id": "pipe_data_31",
        "severity": "critical",
    },
    {
        "id": "inc_seed_003",
        "description": "Gradle build failed: dependency conflict between androidx.core versions",
        "logs": "FAILURE: Build failed with an exception.\nConflict with dependency 'androidx.core:core-ktx'",
        "root_cause": "Gradle dependency conflict: two libraries require incompatible versions of androidx.core",
        "fix": "Add resolutionStrategy.force 'androidx.core:core-ktx:1.15.0' to build.gradle",
        "error_type": "dependency_conflict",
        "pipeline_id": "pipe_android_88",
        "severity": "high",
    },
    {
        "id": "inc_seed_004",
        "description": "Gradle dependency conflict same error as incident #3, recurring 3 weeks later",
        "logs": "FAILURE: Build failed with an exception.\nConflict with dependency 'androidx.core:core'",
        "root_cause": "Gradle dependency conflict: androidx.core version mismatch after library upgrade",
        "fix": "Clear Gradle cache and force androidx.core:1.15.0 in resolutionStrategy",
        "error_type": "dependency_conflict",
        "pipeline_id": "pipe_android_103",
        "severity": "high",
    },
    {
        "id": "inc_seed_005",
        "description": "Docker build failed: no space left on device during layer copy",
        "logs": "ERROR: failed to solve: failed to read dockerfile: no space left on device",
        "root_cause": "CI runner disk full — Docker layer cache consumed all available space",
        "fix": "Run docker system prune -af on the CI runner before builds, or increase disk size",
        "error_type": "disk_full",
        "pipeline_id": "pipe_docker_55",
        "severity": "medium",
    },
    # Demo incident for Blast Radius recall on expressjs/express PR 7233. The
    # response.js / package.json filenames in the text are what make the recall
    # fire (~0.78) when that PR is analyzed. Keep those filenames present.
    {
        "id": "inc_demo_421",
        "description": "content-disposition upgrade broke response.js attachment handling; a package.json dependency bump caused download acceptance test regressions",
        "logs": "TypeError: contentDisposition is not a function\n  at ServerResponse.attachment (lib/response.js:1043)\n  npm ERR! peer dependency mismatch in package.json",
        "root_cause": "Upgrading content-disposition in package.json changed its export shape; lib/response.js called it as the old default export, breaking res.attachment/res.download.",
        "fix": "Update lib/response.js to use the new content-disposition API and pin the version in package.json; re-run download acceptance tests.",
        "error_type": "dependency_upgrade_regression",
        "pipeline_id": "pipe_express_421",
        "severity": "high",
    },
]


@router.get("/status")
async def memory_status() -> dict[str, Any]:
    """Check connectivity and document counts for both memory stores."""
    chroma_count = await chroma.count()
    neo4j_top = await neo4j.get_top_errors(limit=5)

    return {
        "chromadb": {
            "connected": chroma.collection is not None,
            "incident_count": chroma_count,
        },
        "neo4j": {
            "connected": neo4j.driver is not None,
            "top_error_types": neo4j_top,
        },
    }


@router.post("/seed")
async def seed_memory() -> dict[str, Any]:
    """
    Seed both memory stores with demo incidents.
    Safe to call multiple times (upserts, not inserts).
    """
    chroma_ok = 0
    neo4j_ok = 0

    for inc in SEED_INCIDENTS:
        c_result = await chroma.store_incident(
            incident_id=inc["id"],
            description=inc["description"],
            logs=inc["logs"],
            root_cause=inc["root_cause"],
            fix=inc["fix"],
            extra_metadata={
                "title": inc["description"][:80],
                "severity": inc["severity"],
                "status": "resolved",
                "pipeline_id": inc["pipeline_id"],
                "error_type": inc["error_type"],
                "created_at": "2026-06-01T00:00:00Z",
                "resolved_at": "2026-06-01T01:00:00Z",
                "suggested_fix": inc["fix"],
            },
        )
        if c_result:
            chroma_ok += 1

        n_result = await neo4j.store_incident(
            incident_id=inc["id"],
            pipeline_id=inc["pipeline_id"],
            error_type=inc["error_type"],
            fix_description=inc["fix"],
            severity=inc["severity"],
        )
        if n_result:
            neo4j_ok += 1

    return {
        "seeded": len(SEED_INCIDENTS),
        "chromadb_stored": chroma_ok,
        "neo4j_stored": neo4j_ok,
        "incidents": [i["id"] for i in SEED_INCIDENTS],
    }


@router.get("/top-errors")
async def top_errors(limit: int = 10) -> list[dict[str, Any]]:
    """Return most frequent error types from Neo4j."""
    return await neo4j.get_top_errors(limit)


@router.get("/search")
async def search_memory(q: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Direct ChromaDB semantic search (bypasses incident router)."""
    return await chroma.search_similar(q, top_k)


_MOCK_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "inc_seed_001", "label": "Incident"},
        {"id": "inc_seed_002", "label": "Incident"},
        {"id": "inc_seed_003", "label": "Incident"},
        {"id": "inc_seed_004", "label": "Incident"},
        {"id": "inc_seed_005", "label": "Incident"},
        {"id": "pipe_frontend_42", "label": "Pipeline"},
        {"id": "pipe_data_31", "label": "Pipeline"},
        {"id": "pipe_android_88", "label": "Pipeline"},
        {"id": "pipe_android_103", "label": "Pipeline"},
        {"id": "pipe_docker_55", "label": "Pipeline"},
        {"id": "module_resolution_error", "label": "ErrorType"},
        {"id": "out_of_memory", "label": "ErrorType"},
        {"id": "dependency_conflict", "label": "ErrorType"},
        {"id": "disk_full", "label": "ErrorType"},
        {"id": "Add resolve alias to vite.config.js", "label": "Fix"},
        {"id": "Add afterEach hook to release pool connections", "label": "Fix"},
        {"id": "Force androidx.core:1.15.0 in resolutionStrategy", "label": "Fix"},
        {"id": "Run docker system prune before builds", "label": "Fix"},
    ],
    "edges": [
        {"source": "inc_seed_001", "target": "pipe_frontend_42", "type": "CAUSED_BY"},
        {"source": "inc_seed_001", "target": "module_resolution_error", "type": "HAS_ERROR"},
        {"source": "inc_seed_001", "target": "Add resolve alias to vite.config.js", "type": "RESOLVED_BY"},
        {"source": "module_resolution_error", "target": "Add resolve alias to vite.config.js", "type": "FIXED_BY"},
        {"source": "inc_seed_002", "target": "pipe_data_31", "type": "CAUSED_BY"},
        {"source": "inc_seed_002", "target": "out_of_memory", "type": "HAS_ERROR"},
        {"source": "inc_seed_002", "target": "Add afterEach hook to release pool connections", "type": "RESOLVED_BY"},
        {"source": "out_of_memory", "target": "Add afterEach hook to release pool connections", "type": "FIXED_BY"},
        {"source": "inc_seed_003", "target": "pipe_android_88", "type": "CAUSED_BY"},
        {"source": "inc_seed_003", "target": "dependency_conflict", "type": "HAS_ERROR"},
        {"source": "inc_seed_003", "target": "Force androidx.core:1.15.0 in resolutionStrategy", "type": "RESOLVED_BY"},
        {"source": "dependency_conflict", "target": "Force androidx.core:1.15.0 in resolutionStrategy", "type": "FIXED_BY"},
        {"source": "inc_seed_004", "target": "pipe_android_103", "type": "CAUSED_BY"},
        {"source": "inc_seed_004", "target": "dependency_conflict", "type": "HAS_ERROR"},
        {"source": "inc_seed_004", "target": "Force androidx.core:1.15.0 in resolutionStrategy", "type": "RESOLVED_BY"},
        {"source": "inc_seed_005", "target": "pipe_docker_55", "type": "CAUSED_BY"},
        {"source": "inc_seed_005", "target": "disk_full", "type": "HAS_ERROR"},
        {"source": "inc_seed_005", "target": "Run docker system prune before builds", "type": "RESOLVED_BY"},
        {"source": "disk_full", "target": "Run docker system prune before builds", "type": "FIXED_BY"},
    ],
}


@router.get("/graph")
async def get_full_graph() -> dict[str, Any]:
    """Return the full incident knowledge graph (nodes + edges) for visualization."""
    data = await neo4j.get_full_graph()
    if not data["nodes"]:
        return _MOCK_GRAPH
    return data
