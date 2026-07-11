"""
GET /api/integrations/status — single endpoint that probes every external
service and returns a health summary. Used by the dashboard to show
which integrations are live vs. using mock data.
"""
import asyncio
import os
from fastapi import APIRouter
from typing import Any

from core.instances import github, jenkins, n8n, chroma, neo4j, odysseus

router = APIRouter(prefix="/integrations", tags=["integrations"])


async def _check_github() -> dict[str, Any]:
    configured = bool(os.getenv("GITHUB_TOKEN", "").strip())
    if not configured:
        return {"name": "GitHub", "configured": False, "connected": False, "mode": "mock"}
    connected = await github.check_connectivity()
    return {
        "name": "GitHub",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "mock",
        "org": os.getenv("GITHUB_ORG", "(personal)"),
    }


async def _check_jenkins() -> dict[str, Any]:
    # Jenkins is "configured" if we have a URL; token is optional for public read access
    configured = bool(os.getenv("JENKINS_URL", "").strip())
    if not configured:
        return {"name": "Jenkins", "configured": False, "connected": False, "mode": "mock"}
    connected = await jenkins.check_connectivity()
    return {
        "name": "Jenkins",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "mock",
        "url": os.getenv("JENKINS_URL", ""),
        "default_job": os.getenv("JENKINS_DEFAULT_JOB", ""),
    }


async def _check_n8n() -> dict[str, Any]:
    # n8n is reachable even without an API key — webhooks work unauthenticated
    connected = await n8n.check_connectivity()
    api_key_set = bool(os.getenv("N8N_API_KEY", "").strip())
    return {
        "name": "n8n",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "mock",
        "base_url": n8n.base_url,
        "api_key": "set" if api_key_set else "not set (webhooks still work)",
    }


async def _check_chromadb() -> dict[str, Any]:
    connected = chroma.collection is not None
    count = await chroma.count() if connected else 0
    return {
        "name": "ChromaDB",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "no-op",
        "incident_count": count,
        "host": f"{os.getenv('CHROMA_HOST', 'localhost')}:{os.getenv('CHROMA_PORT', '8001')}",
    }


async def _check_neo4j() -> dict[str, Any]:
    connected = neo4j.driver is not None
    top_errors = await neo4j.get_top_errors(limit=3) if connected else []
    return {
        "name": "Neo4j",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "no-op",
        "top_error_types": top_errors,
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    }


async def _check_odysseus() -> dict[str, Any]:
    connected = await odysseus.check_connectivity()
    return {
        "name": "Odysseus",
        "configured": True,
        "connected": connected,
        "mode": "live" if connected else "offline",
        "url": odysseus.base_url,
    }


async def _check_claude() -> dict[str, Any]:
    from core import llm

    provider = llm.active_provider()  # "azure" | "anthropic" | "mock"
    configured = provider != "mock"
    return {
        "name": "AI (LLM)",
        "configured": configured,
        "connected": configured,  # no ping endpoint; assume live if a key is present
        "mode": "live" if configured else "mock",
        "provider": provider,
        "model": llm.provider_label(),
    }


@router.get("/status")
async def integrations_status() -> dict[str, Any]:
    """Probe all external services concurrently and return a health summary."""
    results = await asyncio.gather(
        _check_github(),
        _check_jenkins(),
        _check_n8n(),
        _check_chromadb(),
        _check_neo4j(),
        _check_claude(),
        _check_odysseus(),
        return_exceptions=True,
    )

    services = []
    for r in results:
        if isinstance(r, Exception):
            services.append({"name": "unknown", "connected": False, "error": str(r)})
        else:
            services.append(r)

    live_count = sum(1 for s in services if s.get("connected"))
    return {
        "overall": "healthy" if live_count >= 3 else "degraded" if live_count > 0 else "offline",
        "live_services": live_count,
        "total_services": len(services),
        "services": services,
    }
