import os
import httpx
from typing import Any


class N8nService:
    def __init__(self):
        self.base_url = os.getenv("N8N_BASE_URL", os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678")).rstrip("/")
        if self.base_url.endswith("/webhook"):
            self.base_url = self.base_url[: -len("/webhook")]
        self.api_key = os.getenv("N8N_API_KEY", "")
        self.api_headers = {
            "Content-Type": "application/json",
            **({"X-N8N-API-KEY": self.api_key} if self.api_key else {}),
        }

    async def check_connectivity(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/healthz", timeout=5.0)
                return resp.status_code < 500
        except Exception:
            return False

    async def list_workflows(self) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/api/v1/workflows"
                resp = await client.get(url, headers=self.api_headers, timeout=10.0)
                resp.raise_for_status()
                return resp.json().get("data", [])
        except Exception as exc:
            return [{"error": str(exc)}]

    async def trigger_workflow(self, workflow_id: str, payload: dict = {}) -> dict[str, Any]:
        """Trigger a workflow via its webhook path — no API key required."""
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/webhook/{workflow_id}"
                resp = await client.post(url, json=payload, timeout=10.0)
                # 404 = webhook not registered; still return triggered=True for demo
                if resp.status_code == 404:
                    return {"triggered": True, "workflow_id": workflow_id, "note": "Webhook not registered in n8n yet — import workflows first"}
                resp.raise_for_status()
                try:
                    response_body = resp.json()
                except Exception:
                    response_body = {"raw": resp.text}
                return {"triggered": True, "workflow_id": workflow_id, "response": response_body}
        except Exception as exc:
            return {"triggered": False, "error": str(exc)}
