"""
Public facade for the Aeon agent.
All callers (api/ai.py, etc.) import from here.
The actual LangGraph graph lives in agents/graph.py.
"""
from typing import Any, AsyncIterator

from agents.graph import run_graph, stream_graph, generate_postmortem_doc, TOOL_SCHEMAS, TOOL_MAP, _MOCK_RESULT

# Re-export tool map and schemas for callers that still reference them
TOOLS = TOOL_SCHEMAS
MOCK_RESPONSE = _MOCK_RESULT


async def analyze(query: str, context: dict = {}) -> dict[str, Any]:
    """Run the full LangGraph agent and return the structured result."""
    return await run_graph(query, context)


async def analyze_stream(query: str, context: dict = {}) -> AsyncIterator[dict[str, Any]]:
    """Stream LangGraph node events as they happen."""
    async for event in stream_graph(query, context):
        yield event


async def research_stream(query: str, context: dict = {}) -> AsyncIterator[dict[str, Any]]:
    """Stream deep research mode events."""
    async for event in stream_graph(query, context, mode="research"):
        yield event


async def postmortem(analysis: dict, query: str = "") -> str:
    """Generate a markdown post-mortem from an analysis result."""
    return await generate_postmortem_doc(analysis, query)
