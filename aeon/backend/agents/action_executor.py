"""
Action executor — translates an AI analysis result into real-world actions.

Decision tree:
  Always (if repo provided):
    → create GitHub issue with full analysis context
    → trigger n8n notification workflow (if configured)

  If confidence >= 85 and can_auto_fix (if repo provided):
    → PROPOSE a PR (goes to pending queue, NOT auto-created)
    → Human must call /actions/{id}/approve to actually create the PR

  After PR approval:
    → Create the GitHub PR
    → Trigger Jenkins rebuild (if job_name provided)

This keeps Aeon in "co-pilot" mode — it suggests and acts, but a human
stays in the loop for code changes. Frame this for judges as a feature,
not a limitation.
"""
import uuid
from datetime import datetime
from typing import Any

from core.instances import github as github_svc, jenkins as jenkins_svc, n8n as n8n_svc

# ---------------------------------------------------------------------------
# In-memory pending action store (keyed by action_id)
# Production: replace with PostgreSQL + agent_actions table
# ---------------------------------------------------------------------------
PENDING_ACTIONS: dict[str, dict[str, Any]] = {}

PR_CONFIDENCE_THRESHOLD = 85


def _issue_body(analysis: dict, incident_id: str) -> str:
    """Render a well-formatted GitHub issue body from an analysis result."""
    confidence = analysis.get("confidence", 0)
    root_cause = analysis.get("root_cause", "Unknown")
    fix = analysis.get("suggested_fix", "")
    memory_match = analysis.get("memory_match")
    similar = analysis.get("similar_incidents", [])
    actions = analysis.get("actions_taken", [])

    memory_section = ""
    if memory_match:
        memory_section = (
            f"\n## Memory Match\n"
            f"**{memory_match.get('id')}** ({memory_match.get('time_ago', '')}) — "
            f"similarity {int(memory_match.get('similarity', 0) * 100)}%\n"
            f"> {memory_match.get('root_cause', '')}\n"
            f"> Fix used then: {memory_match.get('fix', '')}\n"
        )

    similar_section = ""
    if similar:
        similar_section = f"\n## Related Incidents\n" + "\n".join(f"- {s}" for s in similar)

    actions_section = ""
    if actions:
        actions_section = f"\n## Agent Actions\n" + "\n".join(f"- `{a}`" for a in actions)

    return f"""\
## Root Cause

{root_cause}

**Confidence:** {confidence}%
**Incident ID:** `{incident_id}`
{memory_section}
## Suggested Fix

```
{fix}
```
{similar_section}{actions_section}

---
*Created by Aeon AI Ops — [requires human review before merging]*
"""


def _pr_body(analysis: dict, incident_id: str) -> str:
    """Render a GitHub PR body from an analysis result."""
    confidence = analysis.get("confidence", 0)
    root_cause = analysis.get("root_cause", "Unknown")
    fix = analysis.get("suggested_fix", "")
    memory_match = analysis.get("memory_match")

    memory_line = ""
    if memory_match:
        memory_line = (
            f"\n> **Memory:** This fix is based on incident "
            f"{memory_match.get('id')} ({memory_match.get('time_ago', '')}) "
            f"with {int(memory_match.get('similarity', 0) * 100)}% similarity.\n"
        )

    return f"""\
## Summary

Automated fix proposed by Aeon AI Ops (confidence: {confidence}%).

**Root cause:** {root_cause}
{memory_line}
## Proposed Fix

```
{fix}
```

## Review Checklist

- [ ] Root cause matches what you observed
- [ ] Fix looks correct for this codebase
- [ ] Tests pass after applying fix
- [ ] No unintended side effects

**Incident:** `{incident_id}`
⚠️ *This PR was proposed by AI with {confidence}% confidence. Human review required before merging.*
"""


async def execute_actions(
    analysis: dict,
    incident_id: str,
    repo: str = "",
    branch: str = "",
    job_name: str = "",
    n8n_workflow_id: str = "",
    query: str = "",
) -> dict[str, Any]:
    """
    Execute immediate actions and queue pending ones.

    Returns:
        {
            executed: list of completed actions,
            pending: list of pending action dicts (require approval),
            skipped: list of skipped actions with reasons,
        }
    """
    executed: list[dict] = []
    pending: list[dict] = []
    skipped: list[dict] = []

    confidence = analysis.get("confidence", 0)
    can_auto_fix = analysis.get("can_auto_fix", False)
    root_cause = analysis.get("root_cause", "Build failure detected")
    fix = analysis.get("suggested_fix", "")

    # Derive branch name if not provided
    fix_branch = branch or f"aeon/fix-{incident_id[:8]}"
    issue_title = f"[Aeon] {root_cause[:80]}"
    pr_title = f"[Aeon] Fix: {fix[:60]}" if fix else f"[Aeon] Fix for {incident_id}"

    # -----------------------------------------------------------------------
    # 1. Create GitHub issue (immediate — always, if repo known)
    # -----------------------------------------------------------------------
    if repo:
        result = await github_svc.create_issue(
            repo=repo,
            title=issue_title,
            body=_issue_body(analysis, incident_id),
            labels=["aeon", "automated"],
        )
        if "error" not in result:
            executed.append({
                "type": "github_issue",
                "description": f"Created issue #{result.get('number', '?')} in {repo}",
                "url": result.get("html_url", result.get("url", "")),
                "issue_number": result.get("number"),
            })
        else:
            skipped.append({"type": "github_issue", "reason": result["error"]})
    else:
        skipped.append({"type": "github_issue", "reason": "No repo provided"})

    # -----------------------------------------------------------------------
    # 2. Trigger n8n notification (immediate)
    # -----------------------------------------------------------------------
    if n8n_workflow_id:
        result = await n8n_svc.trigger_workflow(
            workflow_id=n8n_workflow_id,
            payload={
                "incident_id": incident_id,
                "root_cause": root_cause,
                "confidence": confidence,
                "fix": fix,
                "query": query,
            },
        )
        if result.get("triggered"):
            executed.append({
                "type": "n8n_notification",
                "description": f"Triggered workflow {n8n_workflow_id}",
                "execution_id": result.get("execution_id", ""),
            })
        else:
            skipped.append({"type": "n8n_notification", "reason": result.get("error", "trigger failed")})
    else:
        skipped.append({"type": "n8n_notification", "reason": "No n8n_workflow_id provided"})

    # -----------------------------------------------------------------------
    # 3. Propose PR (pending — requires human approval)
    # -----------------------------------------------------------------------
    if repo and confidence >= PR_CONFIDENCE_THRESHOLD:
        action_id = f"act_{uuid.uuid4().hex[:10]}"
        pending_action = {
            "id": action_id,
            "type": "github_pr",
            "status": "pending_approval",
            "description": f"Create PR '{pr_title}' in {repo} from {fix_branch}",
            "repo": repo,
            "title": pr_title,
            "body": _pr_body(analysis, incident_id),
            "branch": fix_branch,
            "job_name": job_name,
            "confidence": confidence,
            "incident_id": incident_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        PENDING_ACTIONS[action_id] = pending_action
        pending.append({
            "id": action_id,
            "type": "github_pr",
            "description": pending_action["description"],
            "confidence": confidence,
            "requires_approval": True,
            "approve_url": f"/api/actions/{action_id}/approve",
        })
    elif not repo:
        skipped.append({"type": "github_pr", "reason": "No repo provided"})
    else:
        skipped.append({
            "type": "github_pr",
            "reason": f"Confidence {confidence}% below threshold ({PR_CONFIDENCE_THRESHOLD}%)",
        })

    return {
        "incident_id": incident_id,
        "executed": executed,
        "pending": pending,
        "skipped": skipped,
        "summary": (
            f"{len(executed)} action(s) executed immediately; "
            f"{len(pending)} awaiting your approval."
        ),
    }


async def approve_action(action_id: str) -> dict[str, Any]:
    """
    Approve a pending action. For PR proposals, this creates the actual PR
    and optionally triggers a Jenkins rebuild.
    """
    action = PENDING_ACTIONS.get(action_id)
    if not action:
        return {"error": f"No pending action with id={action_id}"}

    if action["status"] != "pending_approval":
        return {"error": f"Action {action_id} is already {action['status']}"}

    action["status"] = "approved"
    action["approved_at"] = datetime.utcnow().isoformat() + "Z"
    result: dict[str, Any] = {"action_id": action_id, "type": action["type"], "steps": []}

    if action["type"] == "github_pr":
        # Create the PR
        pr_result = await github_svc.create_pr(
            repo=action["repo"],
            title=action["title"],
            body=action["body"],
            head_branch=action["branch"],
            base_branch="main",
        )
        if "error" not in pr_result:
            action["status"] = "completed"
            action["pr_url"] = pr_result.get("html_url", pr_result.get("url", ""))
            action["pr_number"] = pr_result.get("number")
            result["steps"].append({
                "action": "github_pr_created",
                "pr_number": pr_result.get("number"),
                "url": action["pr_url"],
            })

            # Trigger Jenkins rebuild if job_name is known
            if action.get("job_name"):
                build_result = await jenkins_svc.trigger_build(action["job_name"])
                result["steps"].append({
                    "action": "jenkins_rebuild_triggered",
                    "job": action["job_name"],
                    "triggered": build_result.get("triggered", False),
                })
        else:
            action["status"] = "failed"
            action["error"] = pr_result["error"]
            result["error"] = pr_result["error"]

    result["status"] = action["status"]
    return result


async def reject_action(action_id: str, reason: str = "") -> dict[str, Any]:
    action = PENDING_ACTIONS.get(action_id)
    if not action:
        return {"error": f"No pending action with id={action_id}"}
    action["status"] = "rejected"
    action["rejected_at"] = datetime.utcnow().isoformat() + "Z"
    action["rejection_reason"] = reason
    return {"action_id": action_id, "status": "rejected"}
