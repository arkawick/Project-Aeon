"""
GraphRAG expansion for the incident agent.

Plain RAG stops at the vector matches. This module takes those matches as
ANCHORS and expands through the incident knowledge graph (Neo4j):

  anchor incident → its error type → proven fixes for that error type (+ how
                    often each was reused) → sibling incidents that hit the same
                    error type on other pipelines.

The result is a compact text block injected into the agent's system prompt
(so the model reasons over the graph, not just the vector hits) plus structured
entities for the UI ("graph context" chips). Degrades to an empty block when
Neo4j is down (mock-fallback rule).
"""

from __future__ import annotations

from typing import Any

from core.instances import neo4j

MAX_ERROR_TYPES = 3
MAX_FIXES_PER_TYPE = 2
MAX_SIBLINGS = 4


def _anchor_error_types(anchor_matches: list[dict]) -> list[str]:
    """Error types to expand from — taken from the matched incidents' metadata."""
    types: list[str] = []
    for m in anchor_matches:
        et = m.get("error_type") or (m.get("metadata") or {}).get("error_type", "")
        if et and et != "ai_analysis" and et not in types:
            types.append(et)
    return types[:MAX_ERROR_TYPES]


async def build_graph_context(anchor_matches: list[dict], query: str = "") -> dict[str, Any]:
    """Expand from the anchor incidents through the Neo4j error/fix graph.

    Returns {"text": <prompt block>, "entities": {...} | None}.
    """
    error_types = _anchor_error_types(anchor_matches)
    if not error_types:
        return {"text": "", "entities": None}

    anchor_ids = {m.get("id") for m in anchor_matches}
    lines: list[str] = ["=== GRAPH KNOWLEDGE (multi-hop expansion from the matches above) ==="]
    entities: dict[str, Any] = {"error_types": [], "fixes": [], "related_incidents": [], "pipelines": []}

    for et in error_types:
        pattern = await neo4j.find_similar_errors(et)   # {records:[{error_type, fixes, occurrence_count}]}
        history = await neo4j.get_error_fix_history(et)  # [{incident_id, pipeline_id, fix, ...}]

        recs = pattern.get("records") or []
        count = recs[0].get("occurrence_count", 0) if recs else len(history)
        fixes = [f for f in (recs[0].get("fixes", []) if recs else []) if f]

        entities["error_types"].append({"error_type": et, "count": count})
        lines.append(f"• error type: {et} ({count} incident(s) on record)")

        # Sibling incidents that hit this error type on other pipelines.
        sibling_ids: list[str] = []
        for h in history:
            iid = h.get("incident_id")
            pid = h.get("pipeline_id")
            if iid and iid not in anchor_ids and iid not in sibling_ids:
                sibling_ids.append(iid)
            if pid and pid not in entities["pipelines"]:
                entities["pipelines"].append(pid)
        sibling_ids = sibling_ids[:MAX_SIBLINGS]
        for s in sibling_ids:
            if s not in entities["related_incidents"]:
                entities["related_incidents"].append(s)
        if sibling_ids:
            lines.append(f"  - also seen in: {', '.join(sibling_ids)}")

        for fx in fixes[:MAX_FIXES_PER_TYPE]:
            lines.append(f"    proven fix: {fx[:160]}")
            if fx not in entities["fixes"]:
                entities["fixes"].append(fx)

    return {"text": "\n".join(lines), "entities": entities}
