"""
Import and activate Aeon workflows into n8n via its REST API.

Usage:
    python import_workflows.py --api-key <your_n8n_api_key>

Or set N8N_API_KEY env var and run:
    python import_workflows.py

The script reads all workflow JSONs from the workflows/ directory,
imports them into n8n, and activates each one.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

N8N_BASE = os.getenv("N8N_BASE_URL", "http://localhost:5678")
WORKFLOWS_DIR = Path(__file__).parent / "workflows"


def api(method: str, path: str, body: dict | None, api_key: str) -> dict:
    url = f"{N8N_BASE}/api/v1{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code}: {body}")
        raise


def import_workflow(workflow_path: Path, api_key: str) -> None:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    name = workflow.get("name", workflow_path.stem)
    print(f"\nImporting: {name}")

    # n8n API only accepts these fields on create/update
    payload = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": workflow.get("settings", {}),
    }

    # Check if already exists
    existing = api("GET", "/workflows", None, api_key).get("data", [])
    match = next((w for w in existing if w["name"] == name), None)

    if match:
        wf_id = match["id"]
        print(f"  Already exists (id={wf_id}), updating...")
        api("PUT", f"/workflows/{wf_id}", {**payload, "id": wf_id}, api_key)
    else:
        result = api("POST", "/workflows", payload, api_key)
        wf_id = result["id"]
        print(f"  Created (id={wf_id})")

    # Activate
    api("POST", f"/workflows/{wf_id}/activate", None, api_key)
    print(f"  Activated")

    # Print webhook URL if it has a webhook trigger
    for node in workflow.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook":
            path_val = node.get("parameters", {}).get("path", "")
            if path_val:
                print(f"  Webhook URL: {N8N_BASE}/webhook/{path_val}")


def main():
    global N8N_BASE
    parser = argparse.ArgumentParser(description="Import Aeon workflows into n8n")
    parser.add_argument("--api-key", default=os.getenv("N8N_API_KEY", ""), help="n8n API key")
    parser.add_argument("--n8n-url", default=N8N_BASE, help="n8n base URL")
    args = parser.parse_args()

    N8N_BASE = args.n8n_url.rstrip("/")

    if not args.api_key:
        print("Error: provide --api-key or set N8N_API_KEY env var")
        print("\nTo get your API key:")
        print("  1. Open http://localhost:5678")
        print("  2. Settings → API → Create an API key")
        sys.exit(1)

    workflow_files = sorted(WORKFLOWS_DIR.glob("*.json"))
    if not workflow_files:
        print(f"No workflow JSONs found in {WORKFLOWS_DIR}")
        sys.exit(1)

    print(f"Found {len(workflow_files)} workflow(s) in {WORKFLOWS_DIR}")

    for wf_file in workflow_files:
        try:
            import_workflow(wf_file, args.api_key)
        except Exception as e:
            print(f"  Failed: {e}")

    print("\nDone. Open http://localhost:5678 to verify.")
    print("\nAdd your API key to aeon/backend/.env:")
    print(f"  N8N_API_KEY={args.api_key}")
    print("Then restart the backend: docker-compose restart backend")


if __name__ == "__main__":
    main()
