"""
Unified LLM provider layer with graceful fallback.

Priority chain:  Azure OpenAI  →  Anthropic  →  (caller falls back to mock)

Every AI surface in Aeon calls `complete()` from here instead of importing a
provider SDK directly. That way a single env change swaps the whole app between
providers, and any provider failure at runtime degrades to the next one.

Azure notes (this deployment is an APIM gateway fronting gpt-5-mini):
  - AZURE_OPENAI_ENDPOINT is the *full* URL incl. deployment path + api-version,
    exactly as tested (…/deployments/gpt-5-mini/chat/completions?api-version=…).
    We POST to it directly rather than letting an SDK rebuild the path.
  - gpt-5-mini is a reasoning model: it wants `max_completion_tokens` (not
    `max_tokens`) and burns hidden `reasoning_tokens`, so we set a generous floor
    to avoid empty/truncated completions.
"""
from __future__ import annotations

import os

import anthropic
import httpx

ANTHROPIC_MODEL = "claude-sonnet-4-6"


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
    if azure_available():
        return "azure"
    if anthropic_available():
        return "anthropic"
    return "mock"


def provider_label() -> str:
    """Human-readable label for status surfaces."""
    if azure_available():
        return f"Azure OpenAI ({os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-5-mini')})"
    if anthropic_available():
        return f"Anthropic ({ANTHROPIC_MODEL})"
    return "mock (no LLM key configured)"


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _azure_token_budget(max_tokens: int) -> int:
    """Reasoning models spend hidden tokens before emitting text — give headroom."""
    return min(max(max_tokens + 2048, 4096), 16000)


async def _azure_complete(system: str, user: str, max_tokens: int) -> str:
    url = os.environ["AZURE_OPENAI_ENDPOINT"].strip()
    key = os.environ["AZURE_OPENAI_API_KEY"].strip()

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    payload = {
        "messages": messages,
        "max_completion_tokens": _azure_token_budget(max_tokens),
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json", "api-key": key},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


async def _anthropic_complete(system: str, user: str, max_tokens: int) -> str:
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"].strip())
    kwargs: dict = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kwargs["system"] = system
    msg = await client.messages.create(**kwargs)
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def complete(system: str, user: str, max_tokens: int = 2000) -> str | None:
    """
    Single-shot completion. Tries Azure first, then Anthropic.

    Returns the text, or None if no provider is configured OR every configured
    provider failed at runtime — callers should treat None as "use mock".
    """
    if azure_available():
        try:
            text = await _azure_complete(system, user, max_tokens)
            if text:
                return text
            # empty completion (e.g. all tokens went to reasoning) — try next
            print("[llm] Azure returned empty content; falling back.")
        except Exception as exc:  # noqa: BLE001 — degrade to next provider
            print(f"[llm] Azure request failed ({exc}); falling back to Anthropic.")

    if anthropic_available():
        try:
            return await _anthropic_complete(system, user, max_tokens)
        except Exception as exc:  # noqa: BLE001
            print(f"[llm] Anthropic request failed ({exc}).")

    return None
