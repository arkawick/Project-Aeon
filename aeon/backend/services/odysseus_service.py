import os
import httpx
from typing import Any


class OdysseusService:
    def __init__(self):
        # When running inside Docker, use host.docker.internal to reach host services.
        # Override via ODYSSEUS_URL in .env if needed.
        self.base_url = os.getenv("ODYSSEUS_URL", "http://host.docker.internal:7000").rstrip("/")

    async def check_connectivity(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(self.base_url)
                return resp.status_code < 500
        except Exception:
            return False

    async def start_research(self, query: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/research/start",
                    json={"query": query, "max_rounds": 5},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    session_id = data.get("session_id", "")
                    return {
                        "success": True,
                        "session_id": session_id,
                        "odysseus_url": self.base_url,
                    }
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "odysseus_url": self.base_url,
                }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "odysseus_url": self.base_url,
            }

    async def send_chat(self, message: str, session_id: str = "") -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                form: dict[str, Any] = {"message": message}
                if session_id:
                    form["session"] = session_id
                resp = await client.post(f"{self.base_url}/api/chat", data=form)
                if resp.status_code == 200:
                    return {"success": True, "response": resp.json(), "odysseus_url": self.base_url}
                return {"success": False, "error": f"HTTP {resp.status_code}", "odysseus_url": self.base_url}
        except Exception as exc:
            return {"success": False, "error": str(exc), "odysseus_url": self.base_url}
