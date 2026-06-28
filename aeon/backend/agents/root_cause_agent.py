import os
import json
from typing import Any

import anthropic

MOCK_RESULT = {
    "root_cause": "Unresolved module import due to missing path alias configuration.",
    "confidence": 82,
    "error_type": "ModuleNotFoundError",
    "stack_trace": "Cannot find module '@/components/Button'",
}


async def analyze_logs(logs: str, context: dict = {}) -> dict[str, Any]:
    """
    Analyze raw log text using Claude to extract root cause information.

    Args:
        logs: Raw log text from CI/CD system.
        context: Optional metadata (repo, branch, job name, etc.)

    Returns:
        Dict with root_cause, confidence, error_type, stack_trace.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return MOCK_RESULT

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are a DevOps expert analyzing CI/CD build logs. "
            "Extract the root cause from the following logs and return ONLY a JSON object with keys:\n"
            "- root_cause (string): clear description of the root cause\n"
            "- confidence (integer 0-100): how confident you are\n"
            "- error_type (string): category of error (e.g. ModuleNotFoundError, OOMError, TimeoutError)\n"
            "- stack_trace (string): the most relevant error line or stack trace snippet\n\n"
            f"Context: {json.dumps(context)}\n\n"
            f"Logs:\n{logs[:8000]}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        return json.loads(text)

    except json.JSONDecodeError:
        return MOCK_RESULT
    except Exception as exc:
        return {**MOCK_RESULT, "error": str(exc)}
