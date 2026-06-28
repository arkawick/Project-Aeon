import os
import json
from typing import Any

import anthropic

SEVERITY_LEVELS = ["critical", "high", "medium", "low"]

MOCK_CLASSIFICATION = {
    "severity": "high",
    "category": "build_failure",
    "priority": 2,
    "auto_resolvable": False,
}

MOCK_FIX = {
    "suggested_fix": "Add path alias configuration to vite.config.js resolve.alias section.",
    "steps": [
        "Open vite.config.js",
        "Add resolve: { alias: { '@': path.resolve(__dirname, 'src') } }",
        "Rebuild the project",
    ],
    "estimated_time": "5 minutes",
    "references": [],
}


async def classify_incident(description: str, logs: str) -> dict[str, Any]:
    """
    Classify an incident by severity using Claude.

    Args:
        description: Human-readable incident description.
        logs: Raw logs associated with the incident.

    Returns:
        Dict with severity, category, priority, auto_resolvable.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return MOCK_CLASSIFICATION

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "Classify this DevOps incident. Return ONLY a JSON object with keys:\n"
            "- severity: one of [critical, high, medium, low]\n"
            "- category: one of [build_failure, deployment_failure, test_failure, infrastructure, security, performance]\n"
            "- priority: integer 1-4 (1=highest)\n"
            "- auto_resolvable: boolean\n\n"
            f"Description: {description}\n\nLogs (excerpt):\n{logs[:3000]}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        return json.loads(text)

    except json.JSONDecodeError:
        return MOCK_CLASSIFICATION
    except Exception as exc:
        return {**MOCK_CLASSIFICATION, "error": str(exc)}


async def suggest_fix(root_cause: str, similar_incidents: list) -> dict[str, Any]:
    """
    Suggest a fix based on root cause and historical incidents.

    Args:
        root_cause: Description of the root cause.
        similar_incidents: List of similar past incidents with their resolutions.

    Returns:
        Dict with suggested_fix, steps, estimated_time, references.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return MOCK_FIX

    try:
        client = anthropic.Anthropic(api_key=api_key)
        history_text = json.dumps(similar_incidents[:5], indent=2) if similar_incidents else "None"
        prompt = (
            "Suggest a fix for this DevOps incident. Return ONLY a JSON object with keys:\n"
            "- suggested_fix (string): one-line fix description\n"
            "- steps (list of strings): ordered steps to resolve\n"
            "- estimated_time (string): time estimate like '5 minutes'\n"
            "- references (list of strings): relevant docs or links\n\n"
            f"Root cause: {root_cause}\n\nSimilar past incidents:\n{history_text}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        return json.loads(text)

    except json.JSONDecodeError:
        return MOCK_FIX
    except Exception as exc:
        return {**MOCK_FIX, "error": str(exc)}
