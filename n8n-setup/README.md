# n8n Setup for Aeon

Configure n8n workflows that are triggered by Aeon when incidents are detected. Two workflows are included:

1. **CI Failure → Slack Notification** — posts a formatted alert to Slack when a build fails
2. **Incident → GitHub Issue** — automatically creates a GitHub issue with Aeon's root cause analysis

---

## Prerequisites

| Requirement | Notes |
|---|---|
| n8n running | `http://localhost:5678` (already in docker-compose) |
| Slack workspace | For workflow 1 (optional — you can skip Slack) |
| GitHub account + token | For workflow 2 (optional) |

---

## Step 1 — Open n8n and complete setup

1. Open **http://localhost:5678**
2. Create a free local account (just an email + password, no external signup needed)
3. Skip the questionnaire

---

## Step 2 — Add credentials

### Slack Incoming Webhook (for workflow 1)

1. Go to **https://api.slack.com/apps** → Create New App → From scratch
2. App Name: `Aeon Alerts` → select your workspace
3. **Incoming Webhooks** → Activate → Add New Webhook to Workspace
4. Choose a channel (e.g. `#ci-alerts`) → Allow
5. Copy the webhook URL: `https://hooks.slack.com/services/T.../B.../xxx`

In n8n:
1. **Credentials** → **Add credential** → search `Slack`
2. Choose **Webhook-Based**: paste your Incoming Webhook URL
3. Name it `Slack Aeon` → Save

### GitHub (for workflow 2)

1. GitHub → Settings → Developer settings → **Personal access tokens (classic)**
2. Generate new token → scopes: `repo` → copy the token

In n8n:
1. **Credentials** → **Add credential** → search `GitHub`
2. Access Token: paste your token
3. Name it `GitHub Aeon` → Save

---

## Step 3 — Import workflows

### Workflow 1: CI Failure → Slack

1. n8n → **Workflows** → **Add Workflow** → **Import from File**
2. Select: `workflows/01-notify-slack.json`
3. Open the **Slack** node → set credential to `Slack Aeon`
4. Edit the **Set Channel** node to use your channel name (default: `#ci-alerts`)
5. Click **Activate** (toggle top-right)
6. Copy the webhook URL from the **Webhook** node (e.g. `http://localhost:5678/webhook/aeon-ci-failure`)

### Workflow 2: Incident → GitHub Issue

1. n8n → **Add Workflow** → **Import from File**
2. Select: `workflows/02-create-github-issue.json`
3. Open the **GitHub** node → set credential to `GitHub Aeon`
4. Edit the **GitHub** node → set Repository Owner and Repository Name
5. Click **Activate**
6. Copy the webhook URL from the **Webhook** node (e.g. `http://localhost:5678/webhook/aeon-incident`)

---

## Step 4 — Configure Aeon to trigger these workflows

The Workflows page in Aeon already has the default webhook IDs (`aeon-ci-failure`, `aeon-incident`). If your workflow URLs are different, update `aeon/backend/api/n8n.py`:

```python
MOCK_WORKFLOWS = [
    {
        "id": "your-actual-webhook-id",  # ← the part after /webhook/
        "name": "Notify Slack on CI Failure",
        ...
    },
]
```

Then restart the backend:
```bash
docker compose restart backend
```

---

## Step 5 — Test it

### Test workflow 1 (Slack notification)
```bash
curl -X POST http://localhost:5678/webhook/aeon-ci-failure \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline": "android-build",
    "status": "failure",
    "error": "Gradle dependency conflict: androidx.core version mismatch",
    "confidence": 91,
    "repo": "acme/android-app",
    "branch": "main"
  }'
```
→ You should receive a Slack message within seconds.

### Test workflow 2 (GitHub issue)
```bash
curl -X POST http://localhost:5678/webhook/aeon-incident \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Android Build Failure",
    "severity": "high",
    "root_cause": "Gradle dependency conflict: androidx.core 1.12.0 vs 1.15.0",
    "fix": "Add resolutionStrategy.force to build.gradle",
    "confidence": 91,
    "incident_id": "aeon_test001"
  }'
```
→ Check your GitHub repo's Issues page for a new issue.

### Trigger from Aeon UI
1. Open http://localhost:3000/workflows
2. Click **Trigger** on either workflow
3. Check n8n → Executions tab to see the run

---

## How Aeon triggers n8n

When the AI assistant completes an analysis and you click **Execute actions**, the backend calls:
```python
await n8n_svc.trigger_workflow("aeon-ci-failure", {
    "pipeline": analysis["name"],
    "error": analysis["root_cause"],
    "confidence": analysis["confidence"],
    ...
})
```
This fires `POST /webhook/aeon-ci-failure` on your local n8n.

You can also trigger manually from `POST /api/n8n/workflows/{id}/trigger`.

---

## Workflow overview

### Workflow 1: CI Failure → Slack
```
Webhook (POST /webhook/aeon-ci-failure)
  → Format Message (Code node: builds Slack block kit message)
  → Slack (sends to #ci-alerts)
  → Respond to Webhook
```

### Workflow 2: Incident → GitHub Issue
```
Webhook (POST /webhook/aeon-incident)
  → Format Issue (Code node: builds issue title + markdown body)
  → GitHub (creates issue with labels: bug, aeon-detected)
  → Respond to Webhook
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| n8n shows "Workflow inactive" | Click the toggle to activate |
| Webhook URL returns 404 | Workflow not activated — activate it first |
| Slack message not arriving | Check the Incoming Webhook URL in the Slack credential |
| GitHub issue not created | Check repo owner/name in the GitHub node; verify token has `repo` scope |
| n8n not reachable | Run `curl http://localhost:5678/healthz` — should return `{"status":"ok"}` |
