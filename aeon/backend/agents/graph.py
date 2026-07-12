"""
LangGraph agent for CI/CD root cause analysis.

Graph shape (Days 11-12 update):
  START → search_memory → call_claude → [execute_tools → call_claude (loop)]
        → synthesize → memory_writer → END

New in Days 11-12:
  - search_memory formats hits with "X weeks ago" language and similarity scores
  - SYSTEM_PROMPT instructs Claude to cite "matches incident {id} from {timeago}"
  - synthesize extracts memory_matches into a rich field on the result
  - memory_writer node stores every result back to ChromaDB + Neo4j
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, TypedDict, Annotated
import operator

import anthropic
from langgraph.graph import StateGraph, END, START

from core.instances import (
    github as github_svc,
    jenkins as jenkins_svc,
    n8n as n8n_svc,
    chroma as chroma_store,
    neo4j as neo4j_store,
)
from core import llm
from services import rerank, graphrag

# Minimum ChromaDB cosine similarity for a hit to be surfaced/cited as a
# "past incident match". Real sentence-embedding scores for genuinely related
# CI/CD incidents land ~0.45–0.65 (the mock's 0.94 was cosmetic), so keep this
# low enough that true matches fire but noise (< ~0.4) does not.
MEMORY_MATCH_THRESHOLD = 0.45

# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    query: str
    context: dict
    mode: str                                          # "quick" | "research"
    messages: list                                     # Claude message history
    memory_context: str                                # pre-fetched, injected into system prompt
    memory_hits: list                                  # raw ChromaDB results
    memory_matches: list                               # rich match objects for the response
    actions_taken: Annotated[list[str], operator.add]
    events: Annotated[list[dict], operator.add]
    result: dict                                       # final structured output
    iteration: int
    evidence: dict                                     # pre-gathered Jenkins build log
    _claude_response: Any                              # LLMTurn from the last call_claude, used by routing

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _time_ago(iso_str: str) -> str:
    """Convert an ISO timestamp to a human-readable relative string."""
    if not iso_str:
        return "some time ago"
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts
        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago" if hours else "just now"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        weeks = days // 7
        if weeks < 5:
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        months = days // 30
        if months < 12:
            return f"{months} month{'s' if months != 1 else ''} ago"
        return f"{days // 365} year{'s' if days // 365 != 1 else ''} ago"
    except Exception:
        return "some time ago"

def _extract_keywords(query: str) -> list[str]:
    """Extract likely error-type keywords from a query string."""
    stopwords = {"why", "did", "the", "fail", "build", "what", "is", "a", "an", "in", "for", "on", "at"}
    words = [w.lower().strip("?.,!") for w in query.split()]
    return [w for w in words if len(w) > 3 and w not in stopwords]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _fetch_jenkins_logs(job_name: str, build_number: int) -> dict[str, Any]:
    return await jenkins_svc.get_build_logs(job_name, build_number)

async def _fetch_github_logs(repo: str, run_id: str) -> dict[str, Any]:
    return await github_svc.get_run_logs(repo, run_id)

async def _search_chromadb_memory(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    return await chroma_store.search_similar(query, top_k)

async def _query_neo4j_graph(query: str) -> dict[str, Any]:
    return await neo4j_store.find_similar_errors(query)

async def _create_github_issue(repo: str, title: str, body: str) -> dict[str, Any]:
    return await github_svc.create_issue(repo, title, body)

async def _create_github_pr(repo: str, title: str, body: str, branch: str) -> dict[str, Any]:
    return await github_svc.create_pr(repo, title, body, branch)

async def _trigger_jenkins_build(job_name: str) -> dict[str, Any]:
    return await jenkins_svc.trigger_build(job_name)

async def _trigger_n8n_workflow(workflow_id: str, payload: dict) -> dict[str, Any]:
    return await n8n_svc.trigger_workflow(workflow_id, payload)

TOOL_MAP = {
    "fetch_jenkins_logs": _fetch_jenkins_logs,
    "fetch_github_logs": _fetch_github_logs,
    "search_chromadb_memory": _search_chromadb_memory,
    "query_neo4j_graph": _query_neo4j_graph,
    "create_github_issue": _create_github_issue,
    "create_github_pr": _create_github_pr,
    "trigger_jenkins_build": _trigger_jenkins_build,
    "trigger_n8n_workflow": _trigger_n8n_workflow,
}

TOOL_SCHEMAS = [
    {
        "name": "fetch_jenkins_logs",
        "description": "Fetch console output from a Jenkins build.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string"},
                "build_number": {"type": "integer"},
            },
            "required": ["job_name", "build_number"],
        },
    },
    {
        "name": "fetch_github_logs",
        "description": "Fetch workflow run logs from GitHub Actions (returns per-job plain text).",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name without owner"},
                "run_id": {"type": "string"},
            },
            "required": ["repo", "run_id"],
        },
    },
    {
        "name": "search_chromadb_memory",
        "description": "Semantic search over past incidents in ChromaDB. Call this first — always.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_neo4j_graph",
        "description": "Query Neo4j for error patterns and their historical fixes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Error type keyword"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_github_issue",
        "description": "Create a GitHub issue to track the incident.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["repo", "title", "body"],
        },
    },
    {
        "name": "create_github_pr",
        "description": "Open a GitHub pull request with the proposed fix.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["repo", "title", "body", "branch"],
        },
    },
    {
        "name": "trigger_jenkins_build",
        "description": "Trigger a Jenkins job to rebuild after a fix.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string"},
            },
            "required": ["job_name"],
        },
    },
    {
        "name": "trigger_n8n_workflow",
        "description": "Trigger an n8n automation (e.g. Slack notification).",
        "input_schema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["workflow_id", "payload"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

DEEP_RESEARCH_PROMPT = """\
You are Aeon, an AI-powered DevOps research agent conducting a DEEP INVESTIGATION.

Your mission is exhaustive — do NOT stop at the first answer. You must:
1. Search incident memory with at least 3 different query angles (e.g. error name, pipeline name, symptom)
2. Fetch logs from Jenkins AND GitHub if available
3. Query Neo4j for patterns across multiple error keywords
4. Cross-reference ALL findings before concluding

When you have fully investigated, respond with ONLY a JSON object with these exact keys:
{
  "title": "Short descriptive incident title",
  "executive_summary": "2-3 sentence summary of what happened and why",
  "root_cause": "Detailed root cause with all evidence cited. Reference memory matches explicitly.",
  "confidence": 85,
  "contributing_factors": ["factor 1", "factor 2"],
  "impact": "What was affected, which pipelines, which teams",
  "resolution": "Step-by-step resolution plan",
  "action_items": ["Preventive action 1", "Preventive action 2"],
  "similar_incidents": ["inc_001"],
  "memory_match": {"id": "inc_001", "time_ago": "3 weeks ago", "fix": "..."},
  "suggested_fix": "Immediate fix command or steps",
  "actions_taken": [],
  "can_auto_fix": false
}

IMPORTANT — Memory matching:
If incident memory contains a match with similarity >= 0.45, you MUST cite it in root_cause using:
  "This matches incident {id} from {timeago} — {what matched}"
Set memory_match to null if no strong match was found.
"""

SYSTEM_PROMPT = """\
You are Aeon, an AI-powered DevOps engineer specializing in CI/CD root cause analysis.

Your job:
1. Use available tools to gather evidence (logs, memory, graph).
2. Identify the root cause with high confidence.
3. Suggest a concrete, actionable fix.
4. Optionally take actions (create issue, PR) if the user requests it.

IMPORTANT — Memory matching:
If the pre-loaded incident memory below contains a match with similarity >= 0.45,
you MUST reference it explicitly in root_cause using this exact format:
  "This matches incident {id} from {timeago} — {brief description of what matched}"
Example: "This matches incident inc_seed_003 from 3 weeks ago — same Gradle dependency conflict resolved by clearing cache."

When you have sufficient evidence, respond with ONLY a JSON object (no markdown fences, no prose) with these exact keys:
{
  "root_cause": "...",
  "confidence": 85,
  "similar_incidents": ["inc_001"],
  "memory_match": {"id": "inc_001", "time_ago": "3 weeks ago", "fix": "..."},
  "suggested_fix": "...",
  "actions_taken": [],
  "can_auto_fix": false
}
Set memory_match to null if no strong match was found.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude's response, handling markdown code fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None

def _summarize_tool_result(name: str, result: Any) -> str:
    if isinstance(result, list):
        return f"{len(result)} result(s)"
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {result['error'][:80]}"
        if "logs" in result:
            lines = str(result["logs"]).strip().splitlines()
            return f"{len(lines)} log lines"
        if "triggered" in result:
            return "triggered" if result["triggered"] else "failed to trigger"
        keys = list(result.keys())[:3]
        return f"{{{', '.join(keys)}, ...}}"
    return str(result)[:80]

def _build_memory_match(hit: dict) -> dict:
    """Convert a raw ChromaDB hit into a rich memory match object."""
    meta = hit.get("metadata", {})
    created_at = meta.get("created_at", "")
    return {
        "id": hit.get("id", ""),
        "time_ago": _time_ago(created_at),
        "created_at": created_at,
        "root_cause": meta.get("root_cause", ""),
        "fix": meta.get("fix", meta.get("suggested_fix", "")),
        "error_type": meta.get("error_type", ""),
        "similarity": hit.get("similarity", 0.0),
        "vector_similarity": hit.get("vector_similarity", hit.get("similarity", 0.0)),
        "match_reasons": hit.get("match_reasons", []),
        "pipeline_id": meta.get("pipeline_id", ""),
    }

# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

async def search_memory_node(state: AgentState) -> dict:
    """
    Pre-flight: search ChromaDB + Neo4j and inject context into system prompt.
    Formats results with relative timestamps so Claude can cite them naturally.
    """
    query = state["query"]
    events: list[dict] = [{"type": "node_start", "node": "search_memory", "message": "Gathering evidence & incident memory..."}]

    # Auto-gather the failing Jenkins build log for the job referenced in the
    # query, so the agent starts grounded in real evidence and recall is enriched
    # with the log text. The agent can still call fetch_jenkins_logs for others.
    evidence = await _gather_jenkins_evidence(query)
    if evidence.get("job"):
        events.append({"type": "tool_call", "tool": "fetch_jenkins_logs",
                       "message": f"Fetching Jenkins logs: {evidence['job']} #{evidence.get('build_number')}..."})
        if evidence.get("logs"):
            lines = len(evidence["logs"].splitlines())
            events.append({"type": "tool_result", "tool": "fetch_jenkins_logs",
                           "message": f"{evidence['job']} #{evidence.get('build_number')} ({evidence.get('result')}) -> {lines} log lines"})
        else:
            events.append({"type": "tool_result", "tool": "fetch_jenkins_logs",
                           "message": f"{evidence['job']}: no log retrievable"})

    search_query = query
    if evidence.get("logs"):
        search_query = f"{query}\n{evidence['logs'][:800]}"

    # Stage 1+2: wide ChromaDB recall → weighted re-rank (cosine + field
    # agreement + recency), write-backs excluded. Blends "reads the same" with
    # "is the same kind of failure" and yields match_reasons for the UI.
    chroma_hits = await rerank.recall(search_query, context=state.get("context"), top_k=3)

    # Build rich match objects
    memory_matches = [_build_memory_match(h) for h in chroma_hits]

    # GraphRAG: expand from the matched incidents through the Neo4j error/fix
    # graph (error type → proven fixes → sibling incidents on other pipelines).
    graph_ctx = await graphrag.build_graph_context(memory_matches, query)

    # Build the memory context string injected into the system prompt
    memory_parts: list[str] = []
    if memory_matches:
        memory_parts.append("=== INCIDENT MEMORY (pre-loaded, cite these if relevant) ===")
        for m in memory_matches:
            sim_pct = int(m["similarity"] * 100)
            why = f" | {', '.join(m['match_reasons'])}" if m.get("match_reasons") else ""
            memory_parts.append(
                f"• [{m['id']}] {m['time_ago']} | match={sim_pct}%{why}\n"
                f"  root_cause: {m['root_cause'][:150]}\n"
                f"  fix: {m['fix'][:150]}"
            )

    if graph_ctx.get("text"):
        memory_parts.append("\n" + graph_ctx["text"])

    memory_context = "\n".join(memory_parts)

    graph_entities = graph_ctx.get("entities") or {}
    best_match = memory_matches[0] if memory_matches and memory_matches[0]["similarity"] >= MEMORY_MATCH_THRESHOLD else None
    events.append({
        "type": "memory_results",
        "chroma_hits": len(chroma_hits),
        "neo4j_patterns": len(graph_entities.get("error_types", [])),
        "best_match": best_match,
        "graph_entities": graph_entities or None,
        "similar_incident_ids": [m["id"] for m in memory_matches],
        "message": (
            f"Found strong match: {best_match['id']} ({best_match['time_ago']})"
            if best_match else
            f"Found {len(chroma_hits)} related incident(s) in memory."
        ),
    })

    return {
        "memory_hits": chroma_hits,
        "memory_matches": memory_matches,
        "memory_context": memory_context,
        "evidence": evidence,
        "events": events,
    }


async def call_claude_node(state: AgentState) -> dict:
    """One agent turn via the provider-agnostic LLM layer (Azure or Anthropic).

    Emits text as text_delta events and returns the normalized LLMTurn for
    routing. Message history is kept in neutral format so it replays to either
    provider across tool-loop iterations.
    """
    system = DEEP_RESEARCH_PROMPT if state.get("mode") == "research" else SYSTEM_PROMPT
    if state.get("memory_context"):
        system += f"\n\n{state['memory_context']}"

    messages = list(state.get("messages", []))
    if not messages:
        # Build the opening user turn, grounding it with the pre-fetched build log.
        parts = [f"Query: {state['query']}"]
        ctx = state.get("context", {})
        if ctx:
            parts.append(f"Context: {json.dumps(ctx)}")
        evidence = state.get("evidence", {})
        if evidence.get("logs"):
            parts.append(
                f"=== JENKINS BUILD LOG — {evidence['job']} #{evidence.get('build_number')} "
                f"(result: {evidence.get('result')}) ===\n{evidence['logs'][:6000]}"
            )
            parts.append(
                "Diagnose the specific root cause from the build log above. Quote the exact "
                "failing line(s). Be concrete and confident; the logs are provided, so do NOT "
                "ask for more. If incident memory contains a match, cite it."
            )
        messages = [{"role": "user", "content": "\n\n".join(parts)}]

    events: list[dict] = [{"type": "node_start", "node": "call_claude",
                           "message": f"Consulting AI ({llm.provider_label()})..."}]

    turn = await llm.run_turn(messages, system, TOOL_SCHEMAS, max_tokens=4096)

    for chunk in turn.text_chunks:
        if chunk:
            events.append({"type": "text_delta", "text": chunk, "message": chunk})

    messages.append(turn.assistant_message)

    tool_names = [tc.name for tc in turn.tool_calls]
    events.append({
        "type": "claude_response",
        "stop_reason": turn.stop_reason,
        "tool_calls": tool_names,
        "message": f"AI wants to call: {', '.join(tool_names)}" if tool_names else "AI is synthesizing...",
    })

    return {
        "messages": messages,
        "events": events,
        "_claude_response": turn,
        "iteration": state.get("iteration", 0) + 1,
    }


async def execute_tools_node(state: AgentState) -> dict:
    """Execute all tool calls from the last agent turn."""
    turn = state["_claude_response"]
    messages = list(state["messages"])
    actions_taken: list[str] = []
    events: list[dict] = [{"type": "node_start", "node": "execute_tools", "message": "Executing tools..."}]
    tool_results = []

    for tc in turn.tool_calls:
        tool_fn = TOOL_MAP.get(tc.name)
        events.append({
            "type": "tool_call",
            "tool": tc.name,
            "args": tc.input,
            "message": f"Calling {tc.name}...",
        })

        if tool_fn:
            try:
                result = await tool_fn(**tc.input)
            except Exception as exc:  # bad args from the model shouldn't kill the loop
                result = {"error": f"{tc.name} failed: {exc}"}
            actions_taken.append(f"{tc.name}({json.dumps(tc.input)[:60]})")
        else:
            result = {"error": f"Unknown tool: {tc.name}"}

        summary = _summarize_tool_result(tc.name, result)
        events.append({
            "type": "tool_result",
            "tool": tc.name,
            "summary": summary,
            "message": f"{tc.name} -> {summary}",
        })
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tc.id,
            "content": json.dumps(result)[:8000],
        })

    messages.append({"role": "user", "content": tool_results})

    return {"messages": messages, "actions_taken": actions_taken, "events": events}


async def synthesize_node(state: AgentState) -> dict:
    """
    Parse Claude's final response into the structured result.
    Merges memory_matches from the pre-flight search into the output.
    """
    turn = state["_claude_response"]
    actions_taken = state.get("actions_taken", [])
    memory_matches = state.get("memory_matches", [])
    events: list[dict] = [{"type": "node_start", "node": "synthesize", "message": "Synthesizing result..."}]

    result: dict | None = _extract_json(turn.text or "")

    if not result:
        # Build a best-effort result from memory alone
        best = memory_matches[0] if memory_matches else None
        result = {
            "root_cause": (
                f"This matches incident {best['id']} from {best['time_ago']} — {best['root_cause']}"
                if best else "Unable to determine root cause — insufficient log data."
            ),
            "confidence": int(best["similarity"] * 100) if best else 40,
            "similar_incidents": [m["id"] for m in memory_matches],
            "memory_match": best,
            "suggested_fix": best["fix"] if best else "Inspect the build logs manually.",
            "actions_taken": actions_taken,
            "can_auto_fix": False,
        }

    # Merge accumulated state into result
    result.setdefault("actions_taken", [])
    result["actions_taken"] = list(dict.fromkeys(result["actions_taken"] + actions_taken))
    result.setdefault("similar_incidents", [m["id"] for m in memory_matches])

    # The real ChromaDB match is authoritative for id/similarity/time_ago — the
    # model often echoes a memory_match with no real similarity (renders as
    # "0% similar" in the UI), so override it with the pre-flight top match.
    if memory_matches and memory_matches[0]["similarity"] >= MEMORY_MATCH_THRESHOLD:
        result["memory_match"] = memory_matches[0]

    # Attach full memory_matches list for the UI cards
    result["memory_matches"] = memory_matches

    events.append({
        "type": "result",
        "content": result,
        "message": "Analysis complete.",
    })
    if result.get("memory_match"):
        m = result["memory_match"]
        events.append({
            "type": "memory_match_found",
            "incident_id": m.get("id"),
            "time_ago": m.get("time_ago"),
            "message": f"Matched incident {m.get('id')} from {m.get('time_ago')}",
        })

    return {"result": result, "events": events}


async def memory_writer_node(state: AgentState) -> dict:
    """
    Store every analysis result back to ChromaDB + Neo4j so the agent
    learns from every query. This is what makes Aeon smarter over time.
    """
    result = state.get("result", {})
    query = state.get("query", "")
    context = state.get("context", {})
    evidence = state.get("evidence", {})
    events: list[dict] = [{"type": "node_start", "node": "memory_writer", "message": "Storing to memory..."}]

    root_cause = result.get("root_cause", "")
    fix = result.get("suggested_fix", "")

    if not root_cause or not fix:
        events.append({"type": "memory_written", "stored": False, "message": "Nothing to store."})
        return {"events": events}

    incident_id = f"aeon_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat() + "Z"
    # Prefer the auto-gathered evidence's job/log when the caller gave no context.
    error_type = context.get("error_type") or ("build_failure" if evidence.get("logs") else "ai_analysis")
    pipeline_id = context.get("pipeline_id") or evidence.get("job") or "unknown"
    logs = context.get("logs") or evidence.get("logs", "")

    chroma_ok = await chroma_store.store_incident(
        incident_id=incident_id,
        description=query,
        logs=logs,
        root_cause=root_cause,
        fix=fix,
        extra_metadata={
            "title": query[:80],
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
    neo4j_ok = await neo4j_store.store_incident(
        incident_id=incident_id,
        pipeline_id=pipeline_id,
        error_type=error_type,
        fix_description=fix,
        severity="medium",
    )

    events.append({
        "type": "memory_written",
        "incident_id": incident_id,
        "stored": chroma_ok or neo4j_ok,
        "message": f"Stored as {incident_id}",
    })
    return {"events": events}

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 8
MAX_RESEARCH_ITERATIONS = 15

def _should_continue(state: AgentState) -> str:
    response = state.get("_claude_response")
    limit = MAX_RESEARCH_ITERATIONS if state.get("mode") == "research" else MAX_ITERATIONS
    if response and response.stop_reason == "tool_use" and state.get("iteration", 0) < limit:
        return "execute_tools"
    return "synthesize"

# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("search_memory", search_memory_node)
    g.add_node("call_claude", call_claude_node)
    g.add_node("execute_tools", execute_tools_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("memory_writer", memory_writer_node)

    g.add_edge(START, "search_memory")
    g.add_edge("search_memory", "call_claude")
    g.add_conditional_edges("call_claude", _should_continue, {
        "execute_tools": "execute_tools",
        "synthesize": "synthesize",
    })
    g.add_edge("execute_tools", "call_claude")
    g.add_edge("synthesize", "memory_writer")  # always write back to memory
    g.add_edge("memory_writer", END)

    return g.compile()


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MOCK_RESULT = {
    "root_cause": (
        "This matches incident inc_seed_003 from 3 weeks ago — "
        "same Gradle dependency conflict, resolved by clearing cache and forcing androidx.core:1.15.0."
    ),
    "confidence": 91,
    "similar_incidents": ["inc_seed_003", "inc_seed_004"],
    "memory_match": {
        "id": "inc_seed_003",
        "time_ago": "3 weeks ago",
        "root_cause": "Gradle dependency conflict: incompatible androidx.core versions",
        "fix": "Add resolutionStrategy.force 'androidx.core:core-ktx:1.15.0' to build.gradle",
        "similarity": 0.94,
    },
    "memory_matches": [
        {
            "id": "inc_seed_003",
            "time_ago": "3 weeks ago",
            "root_cause": "Gradle dependency conflict: incompatible androidx.core versions",
            "fix": "Add resolutionStrategy.force 'androidx.core:core-ktx:1.15.0' to build.gradle",
            "similarity": 0.94,
        }
    ],
    "suggested_fix": "Add resolutionStrategy.force 'androidx.core:core-ktx:1.15.0' to build.gradle",
    "actions_taken": [],
    "can_auto_fix": False,
}


_MOCK_RESEARCH_RESULT = {
    **_MOCK_RESULT,
    "title": "Android Gradle Build Failure — androidx.core Version Conflict",
    "executive_summary": (
        "The Android build pipeline failed due to an unresolved Gradle dependency conflict between "
        "two versions of androidx.core. This is a recurring pattern — the same conflict was seen in "
        "inc_seed_003 three weeks ago and inc_seed_004 shortly after. Both were resolved by forcing "
        "androidx.core:1.15.0 in the resolutionStrategy block."
    ),
    "contributing_factors": [
        "Library upgrade introduced a transitive dependency on a newer androidx.core version",
        "No resolutionStrategy.force in build.gradle to pin the version",
        "Missing automated dependency conflict detection in CI pipeline",
    ],
    "impact": "Android build pipeline fully blocked. No APK produced. Affects all downstream staging deploys.",
    "resolution": (
        "1. Add `resolutionStrategy.force 'androidx.core:core-ktx:1.15.0'` to build.gradle\n"
        "2. Clear Gradle cache: `./gradlew clean`\n"
        "3. Re-trigger android-build pipeline\n"
        "4. Add dependency conflict lint step to prevent recurrence"
    ),
    "action_items": [
        "Pin androidx.core version in resolutionStrategy",
        "Add Gradle dependency conflict detection step to CI",
        "Review recent library upgrades that introduced the transitive dependency",
    ],
}


# ---------------------------------------------------------------------------
# Agent helpers (shared by the LangGraph nodes on both providers)
# ---------------------------------------------------------------------------
# The tool-calling loop runs on Azure OR Anthropic via llm.run_turn. These
# helpers build a best-effort result from incident memory when the model returns
# no JSON, fold the real memory match into the result, and auto-gather the
# failing Jenkins build log so the agent starts grounded in real evidence.

def _memory_fallback_result(memory_matches: list, mode: str = "quick") -> dict:
    """Build a result from incident memory alone when the LLM returns no JSON."""
    best = memory_matches[0] if memory_matches else None
    return {
        "root_cause": (
            f"This matches incident {best['id']} from {best['time_ago']} — {best['root_cause']}"
            if best else "Unable to determine root cause — insufficient log data."
        ),
        "confidence": int(best["similarity"] * 100) if best else 40,
        "similar_incidents": [m["id"] for m in memory_matches],
        "memory_match": best,
        "suggested_fix": best["fix"] if best else "Inspect the build logs manually.",
        "actions_taken": [],
        "can_auto_fix": False,
    }


def _merge_memory(result: dict, memory_matches: list) -> dict:
    """Fold the pre-flight memory matches into an LLM-produced result.

    The real ChromaDB match is authoritative for id/similarity/time_ago — the
    model often echoes a memory_match without a real similarity, which would
    render as "0% similar" in the UI.
    """
    result.setdefault("actions_taken", [])
    result.setdefault("similar_incidents", [m["id"] for m in memory_matches])
    if memory_matches and memory_matches[0]["similarity"] >= MEMORY_MATCH_THRESHOLD:
        result["memory_match"] = memory_matches[0]
    result["memory_matches"] = memory_matches
    return result


_JOB_NAME_STOPWORDS = {"the", "a", "an", "job", "pipeline", "why", "did", "fail", "failed", "failing"}


async def _gather_jenkins_evidence(query: str) -> dict:
    """
    Detect which Jenkins job the query is about and fetch its failing build log,
    so the single-shot path has real evidence instead of guessing.
    Returns {job, build_number, result, logs} or {} if nothing matched.
    """
    try:
        jobs = await jenkins_svc.list_jobs()
    except Exception:
        return {}
    if not jobs or (isinstance(jobs[0], dict) and jobs[0].get("error")):
        return {}

    q = query.lower()
    q_tokens = set(re.findall(r"[a-z0-9]+", q))
    best, best_score, best_is_failure = None, 0, False

    for j in jobs:
        name = j.get("name", "")
        if not name:
            continue
        if name.lower() in q:
            score = 100  # exact job name mentioned
        else:
            name_tokens = set(re.split(r"[-_]", name.lower())) - _JOB_NAME_STOPWORDS
            score = len(name_tokens & q_tokens)
        if score == 0:
            continue
        is_failure = (j.get("lastBuild") or {}).get("result") == "FAILURE"
        # higher score wins; on a tie, prefer a job that actually failed
        if score > best_score or (score == best_score and is_failure and not best_is_failure):
            best, best_score, best_is_failure = j, score, is_failure

    if not best:
        return {}

    name = best["name"]
    builds = await jenkins_svc.get_builds(name, limit=10)
    target = next((b for b in builds if isinstance(b, dict) and b.get("result") == "FAILURE"), None)
    if target is None:
        target = best.get("lastBuild") or (builds[0] if builds and isinstance(builds[0], dict) and not builds[0].get("error") else None)
    if not target or target.get("number") is None:
        return {"job": name, "logs": ""}

    num = target["number"]
    log_res = await jenkins_svc.get_build_logs(name, num)
    return {
        "job": name,
        "build_number": num,
        "result": target.get("result") or (best.get("lastBuild") or {}).get("result"),
        "logs": log_res.get("logs") or "",
    }


def _initial_state(query: str, context: dict, mode: str) -> "AgentState":
    return {
        "query": query,
        "context": context,
        "mode": mode,
        "messages": [],
        "memory_context": "",
        "memory_hits": [],
        "memory_matches": [],
        "evidence": {},
        "actions_taken": [],
        "events": [],
        "result": {},
        "iteration": 0,
        "_claude_response": None,
    }


async def run_graph(query: str, context: dict = {}, mode: str = "quick") -> dict[str, Any]:
    """Run the LangGraph tool-calling agent and return the structured result.

    The agent runs on whichever provider llm.active_provider() selects (Azure or
    Anthropic) via the provider-agnostic run_turn; with no provider, returns mock.
    """
    mock = _MOCK_RESEARCH_RESULT if mode == "research" else _MOCK_RESULT
    if not llm.llm_available():
        return mock
    try:
        final = await get_graph().ainvoke(_initial_state(query, context, mode))
        return final.get("result") or mock
    except Exception as exc:
        return {**mock, "error": str(exc)}


async def stream_graph(query: str, context: dict = {}, mode: str = "quick") -> AsyncIterator[dict[str, Any]]:
    """Stream agent node events as they happen. Yields dicts for SSE."""
    mock_result = _MOCK_RESEARCH_RESULT if mode == "research" else _MOCK_RESULT

    if not llm.llm_available():
        yield {"type": "node_start", "node": "search_memory", "message": "Searching incident memory..."}
        yield {
            "type": "memory_results",
            "chroma_hits": 1,
            "neo4j_patterns": 0,
            "message": "Found strong match: inc_seed_003 (3 weeks ago)",
        }
        yield {"type": "node_start", "node": "call_claude", "message": "Consulting AI..."}
        mock_text = mock_result.get("executive_summary") or mock_result["root_cause"]
        for word in mock_text.split():
            yield {"type": "text_delta", "text": word + " ", "message": word + " "}
        yield {"type": "claude_response", "stop_reason": "end_turn", "tool_calls": [], "message": "AI is synthesizing..."}
        yield {"type": "node_start", "node": "synthesize", "message": "Synthesizing result..."}
        yield {"type": "result", "content": mock_result, "message": "Analysis complete (mock)."}
        yield {"type": "memory_written", "stored": True, "message": "Stored as aeon_mock0001"}
        return

    try:
        async for chunk in get_graph().astream(_initial_state(query, context, mode), stream_mode="updates"):
            for _node_name, node_output in chunk.items():
                for event in node_output.get("events", []):
                    yield event
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}


async def generate_postmortem_doc(analysis: dict, query: str = "") -> str:
    """Format an analysis result as a markdown post-mortem via the active LLM provider."""
    if not llm.llm_available():
        return _build_mock_postmortem(analysis, query)

    prompt = (
        f"You are a senior DevOps engineer writing an incident post-mortem.\n"
        f"Given the following AI analysis result, produce a complete, professional post-mortem "
        f"in Markdown format. Include sections: Title, Date, Severity, Executive Summary, "
        f"Timeline (infer reasonable times), Root Cause, Contributing Factors, Impact, "
        f"Resolution, Action Items (as checkboxes), and Similar Past Incidents.\n\n"
        f"Original query: {query}\n\n"
        f"Analysis:\n{json.dumps(analysis, indent=2)}\n\n"
        f"Write only the Markdown document, no preamble."
    )
    text = await llm.complete(system="", user=prompt, max_tokens=2048)
    return text or _build_mock_postmortem(analysis, query)


def _build_mock_postmortem(analysis: dict, query: str) -> str:
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    title = analysis.get("title") or query or "CI/CD Build Failure"
    confidence = analysis.get("confidence", 0)
    severity = "Critical" if confidence >= 90 else "High" if confidence >= 75 else "Medium"
    fix = analysis.get("suggested_fix", "See analysis above.")
    root_cause = analysis.get("root_cause", "Unknown")
    factors = analysis.get("contributing_factors", ["See root cause analysis"])
    impact = analysis.get("impact", "Build pipeline blocked, deployments halted.")
    resolution = analysis.get("resolution", fix)
    action_items = analysis.get("action_items", ["Apply suggested fix", "Monitor pipeline"])
    similar = analysis.get("similar_incidents", [])

    factors_md = "\n".join(f"- {f}" for f in factors)
    actions_md = "\n".join(f"- [ ] {a}" for a in action_items)
    similar_md = ", ".join(similar) if similar else "None recorded"

    return f"""# Post-Mortem: {title}

**Date:** {today}
**Severity:** {severity}
**Confidence:** {confidence}%
**Status:** Resolved

---

## Executive Summary

{analysis.get("executive_summary", root_cause)}

---

## Timeline

| Time | Event |
|---|---|
| T+0 | Build triggered |
| T+1m | Pipeline failure detected |
| T+5m | Aeon AI analysis initiated |
| T+10m | Root cause identified |
| T+15m | Fix applied and pipeline re-triggered |

---

## Root Cause

{root_cause}

---

## Contributing Factors

{factors_md}

---

## Impact

{impact}

---

## Resolution

{resolution}

---

## Action Items

{actions_md}

---

## Similar Past Incidents

{similar_md}

---

*Generated by Aeon AI on {today}*
"""
