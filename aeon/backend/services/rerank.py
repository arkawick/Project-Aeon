"""
Two-stage retrieval for incident memory.

Stage 1: ChromaDB vector recall of a wide candidate set (RECALL_K).
Stage 2: weighted re-rank blending cosine similarity with domain-field
agreement (error_type / pipeline_id / source / repo) and recency, plus an
optional fix-evidence filter so only incidents with a concrete fix feed
recommendations.

Pattern adapted from Aeon's automotive sibling project: pure vector similarity
finds "reads the same"; field agreement confirms "is the same kind of failure".
The blend beats either alone, and it emits human-readable match_reasons the UI
can show ("same error_type", "62% semantic").
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.instances import chroma

RECALL_K = 10  # wide vector recall before re-rank

# Weights sum to 1.0 — vector similarity dominates, fields confirm.
WEIGHTS = {
    "vector":      0.60,
    "error_type":  0.15,
    "pipeline_id": 0.10,
    "source":      0.05,
    "repo":        0.05,
    "recency":     0.05,
}

# The agent's own auto-analysis write-backs — excluded from grounding recall so
# a re-run of the same query doesn't match its own previous output.
WRITEBACK_STATUS = "analyzed"


def _tokenize(s: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()) - {""}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _soft_eq(a: str, b: str) -> float:
    """Exact match → 1.0; otherwise weak fuzzy token overlap."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return _jaccard(a, b) * 0.6


def _recency(created_at: str) -> float:
    """Recent incidents matter more: ≤90 days → 1.0, ≤1 year → 0.5, older → 0.2."""
    if not created_at:
        return 0.0
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - ts).days
    except ValueError:
        return 0.0
    if days <= 90:
        return 1.0
    if days <= 365:
        return 0.5
    return 0.2


def has_fix_evidence(meta: dict) -> bool:
    """An incident contributes to recommendations only with a concrete fix."""
    return bool((meta.get("fix") or meta.get("suggested_fix") or "").strip())


def rerank_hits(hits: list[dict], query_text: str, context: dict | None = None) -> list[dict]:
    """Re-score chroma hits by the blended score (descending).

    context may carry any of: error_type, pipeline_id, source, repo. Fields
    absent from the query context fold their weight onto text overlap with the
    stored document, so scores stay comparable whether or not context is rich.
    """
    context = context or {}
    scored = []
    for h in hits:
        meta = h.get("metadata", {})
        vector_sim = float(h.get("similarity", 0.0))

        score = WEIGHTS["recency"] * _recency(meta.get("created_at", ""))
        # Absent context fields reinforce the semantic signal rather than
        # penalizing a hit — our queries are log-enriched, so raw text overlap
        # is an unreliable substitute for structured field agreement.
        vector_weight = WEIGHTS["vector"]
        reasons: list[str] = []
        for field, w in (("error_type", WEIGHTS["error_type"]), ("pipeline_id", WEIGHTS["pipeline_id"]),
                         ("source", WEIGHTS["source"]), ("repo", WEIGHTS["repo"])):
            if context.get(field):
                s = _soft_eq(context[field], meta.get(field, ""))
                score += w * s
                if s >= 0.99:
                    reasons.append(f"same {field}")
            else:
                vector_weight += w
        score += vector_weight * vector_sim

        if vector_sim >= 0.45:
            reasons.insert(0, f"{int(vector_sim * 100)}% semantic")

        scored.append({
            **h,
            "similarity": round(min(score, 1.0), 4),    # blended — what the UI shows
            "vector_similarity": round(vector_sim, 4),   # raw cosine, kept for transparency
            "match_reasons": reasons,
        })

    scored.sort(key=lambda x: -x["similarity"])
    return scored


async def recall(
    query_text: str,
    context: dict | None = None,
    top_k: int = 3,
    require_fix_evidence: bool = False,
    exclude_writebacks: bool = True,
) -> list[dict]:
    """Two-stage retrieval: wide vector recall → drop write-backs → weighted
    re-rank → top_k."""
    hits = await chroma.search_similar(query_text, top_k=RECALL_K)
    if not hits:
        return []

    if exclude_writebacks:
        curated = [h for h in hits if (h.get("metadata") or {}).get("status") != WRITEBACK_STATUS]
        hits = curated or hits  # nothing curated matched → fall back to whatever we found

    if require_fix_evidence:
        with_fix = [h for h in hits if has_fix_evidence(h.get("metadata", {}))]
        if with_fix:
            hits = with_fix

    return rerank_hits(hits, query_text, context)[:top_k]
