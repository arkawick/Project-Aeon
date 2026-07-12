"""
Unified, provider-agnostic LLM layer.

Priority chain:  Azure OpenAI  →  Anthropic  →  (caller falls back to mock)

Every AI surface in Aeon calls this module instead of a provider SDK directly,
so a single env change swaps the whole app between providers, and the LangGraph
agent's tool-calling loop runs on EITHER provider.

Two public surfaces:
  - complete(system, user, max_tokens)  → single-shot text (blast/provenance/
    cochange/post-mortem). Kept stable for existing callers.
  - run_turn(messages, system, tools, max_tokens) → one tool-calling agent turn,
    returned as a normalized LLMTurn whose assistant_message is neutral-format
    so it can be replayed to either provider on the next iteration.

Neutral message format (Anthropic-shaped; translated to OpenAI for Azure):
    {"role": "user"|"assistant", "content": <str> | [parts]}
    parts: {"type":"text","text":...}
           {"type":"tool_use","id":...,"name":...,"input":{...}}       (assistant)
           {"type":"tool_result","tool_use_id":...,"content":"..."}    (user)
Tool schemas are Anthropic-shaped: {"name","description","input_schema"}.

Azure notes (this deployment is an APIM gateway fronting gpt-5-mini):
  - AZURE_OPENAI_ENDPOINT is the full URL incl. deployment path (+ optional
    ?api-version / trailing /chat/completions, both stripped automatically).
  - gpt-5-mini is a reasoning model → uses max_completion_tokens with headroom.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

ANTHROPIC_MODEL = os.getenv("CLAUDE_MODEL_ID", "claude-sonnet-4-6")


# ---------------------------------------------------------------------------
# Availability / provider selection
# ---------------------------------------------------------------------------

def azure_available() -> bool:
    return bool(
        os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        and os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    )


def anthropic_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def llm_available() -> bool:
    """True if at least one live provider is configured."""
    return azure_available() or anthropic_available()


def active_provider() -> str:
    """The provider that will actually serve a request right now."""
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced == "azure":
        return "azure" if azure_available() else "mock"
    if forced == "anthropic":
        return "anthropic" if anthropic_available() else "mock"
    if forced in ("none", "mock", "off"):
        return "mock"
    if azure_available():
        return "azure"
    if anthropic_available():
        return "anthropic"
    return "mock"


def model_name() -> str:
    p = active_provider()
    if p == "azure":
        return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")
    if p == "anthropic":
        return ANTHROPIC_MODEL
    return "mock"


def provider_label() -> str:
    """Human-readable label for status surfaces."""
    p = active_provider()
    if p == "azure":
        return f"Azure OpenAI ({model_name()})"
    if p == "anthropic":
        return f"Anthropic ({model_name()})"
    return "mock (no LLM key configured)"


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def _anthropic_client():
    import anthropic
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())


def _azure_client():
    """Build an AsyncOpenAI client for the configured Azure endpoint.

    Handles two shapes:
      1. Standard Azure resource (host ends with .openai.azure.com) → AsyncAzureOpenAI.
      2. APIM / custom gateway whose route already embeds the deployment path →
         AsyncOpenAI at that base_url, api-version as a query param, key as an
         `api-key` header. A trailing /chat/completions or ?query is stripped, so
         pasting the full tested URL works as-is.
    """
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    parts = urlsplit(os.getenv("AZURE_OPENAI_ENDPOINT", "").strip())

    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    host = parts.netloc.lower()

    if host.endswith(".openai.azure.com") and path in ("", "/"):
        from openai import AsyncAzureOpenAI
        return AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=f"{parts.scheme}://{parts.netloc}",
            api_version=api_version,
        )

    from openai import AsyncOpenAI
    base_url = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return AsyncOpenAI(
        api_key=api_key or "gateway",
        base_url=base_url,
        default_query={"api-version": api_version},
        default_headers={"api-key": api_key},
    )


def _azure_deployment() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")


def _azure_max_tokens(max_tokens: int) -> int:
    """Reasoning models spend hidden tokens before emitting text — give headroom."""
    return min(max(max_tokens, 4096), 16000)


# ---------------------------------------------------------------------------
# Neutral -> OpenAI translation
# ---------------------------------------------------------------------------

def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            texts = [p["text"] for p in content if p.get("type") == "text"]
            tool_uses = [p for p in content if p.get("type") == "tool_use"]
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            if tool_uses:
                msg["tool_calls"] = [{
                    "id": p["id"], "type": "function",
                    "function": {"name": p["name"], "arguments": json.dumps(p.get("input", {}))},
                } for p in tool_uses]
            out.append(msg)
        else:  # user — may carry text and/or tool_result parts
            texts = [p["text"] for p in content if p.get("type") == "text"]
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
            for tr in [p for p in content if p.get("type") == "tool_result"]:
                out.append({"role": "tool", "tool_call_id": tr["tool_use_id"],
                            "content": tr["content"]})
    return out


def _to_openai_tools(tools: list[dict] | None) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
        },
    } for t in (tools or [])]


def _wordsplit(text: str) -> list[str]:
    return [w + " " for w in text.split(" ")] if text else []


# ---------------------------------------------------------------------------
# Single-shot completion  (stable API for blast/provenance/cochange/postmortem)
# ---------------------------------------------------------------------------

async def _azure_complete(system: str, user: str, max_tokens: int) -> str:
    client = _azure_client()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    resp = await client.chat.completions.create(
        model=_azure_deployment(),
        messages=messages,
        max_completion_tokens=_azure_max_tokens(max_tokens),
    )
    return (resp.choices[0].message.content or "").strip()


async def _anthropic_complete(system: str, user: str, max_tokens: int) -> str:
    client = _anthropic_client()
    kwargs: dict = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": user}]}
    if system:
        kwargs["system"] = system
    msg = await client.messages.create(**kwargs)
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""


async def complete(system: str, user: str, max_tokens: int = 2000) -> str | None:
    """Single-shot completion. Azure first, then Anthropic.

    Returns text, or None if no provider is configured OR every configured
    provider failed — callers should treat None as "use mock".
    """
    if azure_available():
        try:
            text = await _azure_complete(system, user, max_tokens)
            if text:
                return text
            print("[llm] Azure returned empty content; falling back.")
        except Exception as exc:  # noqa: BLE001
            print(f"[llm] Azure request failed ({exc}); falling back to Anthropic.")
    if anthropic_available():
        try:
            return await _anthropic_complete(system, user, max_tokens)
        except Exception as exc:  # noqa: BLE001
            print(f"[llm] Anthropic request failed ({exc}).")
    return None


# ---------------------------------------------------------------------------
# Tool-calling turn  (for the LangGraph agent — provider-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMTurn:
    text: str
    text_chunks: list[str]
    tool_calls: list[ToolCall]
    stop_reason: str            # "tool_use" | "end_turn"
    assistant_message: dict     # neutral assistant message to append to history


async def run_turn(messages: list[dict], system: str, tools: list[dict],
                   max_tokens: int = 4096) -> LLMTurn:
    """One agent turn with tool-calling. Azure first, then Anthropic.

    The returned assistant_message is neutral-format so it can be appended to the
    running history and replayed to either provider on the next iteration.
    """
    p = active_provider()

    if p == "azure":
        client = _azure_client()
        resp = await client.chat.completions.create(
            model=_azure_deployment(),
            messages=_to_openai_messages(messages, system),
            tools=_to_openai_tools(tools) or None,
            tool_choice="auto" if tools else None,
            max_completion_tokens=_azure_max_tokens(max_tokens),
        )
        choice = resp.choices[0]
        m = choice.message
        text = m.content or ""
        parts: list[dict] = []
        if text:
            parts.append({"type": "text", "text": text})
        tool_calls: list[ToolCall] = []
        for tc in (m.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            parts.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": args})
            tool_calls.append(ToolCall(tc.id, tc.function.name, args))
        stop = "tool_use" if (tool_calls or choice.finish_reason == "tool_calls") else "end_turn"
        return LLMTurn(text, _wordsplit(text), tool_calls, stop,
                       {"role": "assistant", "content": parts or [{"type": "text", "text": ""}]})

    if p == "anthropic":
        client = _anthropic_client()
        chunks: list[str] = []
        async with client.messages.stream(
            model=ANTHROPIC_MODEL, max_tokens=max_tokens, system=system,
            tools=tools, messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    chunks.append(text)
            resp = await stream.get_final_message()
        parts = []
        tool_calls = []
        for b in resp.content:
            if b.type == "text":
                parts.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                parts.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                tool_calls.append(ToolCall(b.id, b.name, b.input))
        text = "".join(pt["text"] for pt in parts if pt["type"] == "text")
        stop = "tool_use" if resp.stop_reason == "tool_use" else "end_turn"
        return LLMTurn(text, chunks or _wordsplit(text), tool_calls, stop,
                       {"role": "assistant", "content": parts or [{"type": "text", "text": ""}]})

    raise RuntimeError("No LLM provider configured")
