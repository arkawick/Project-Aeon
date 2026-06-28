import os
import httpx
from typing import Any


class JenkinsService:
    def __init__(self):
        self.url = os.getenv("JENKINS_URL", "http://localhost:8080").rstrip("/")
        self.user = os.getenv("JENKINS_USER", "admin")
        # JENKINS_TOKEN can be an API token OR the plain password for local instances.
        # When set, basic auth (user, token) is used. When empty, anonymous access is tried.
        self.token = os.getenv("JENKINS_TOKEN", "")
        self.auth = (self.user, self.token) if self.token else None

    async def check_connectivity(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.url}/api/json",
                    auth=self.auth,
                    timeout=5.0,
                )
                return resp.status_code in (200, 403)  # 403 = up but needs auth
        except Exception:
            return False

    async def get_builds(self, job_name: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.url}/job/{job_name}/api/json"
                params = {"tree": f"builds[number,status,result,duration,timestamp]{{0,{limit}}}"}
                resp = await client.get(url, auth=self.auth, params=params, timeout=10.0)
                resp.raise_for_status()
                return resp.json().get("builds", [])
        except Exception as exc:
            return [{"error": str(exc)}]

    async def get_build_logs(self, job_name: str, build_number: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.url}/job/{job_name}/{build_number}/consoleText"
                resp = await client.get(url, auth=self.auth, timeout=15.0)
                resp.raise_for_status()
                return {"logs": resp.text, "job": job_name, "build_number": build_number}
        except Exception as exc:
            return {"error": str(exc), "logs": ""}

    async def trigger_build(self, job_name: str, params: dict = {}) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                if params:
                    url = f"{self.url}/job/{job_name}/buildWithParameters"
                    resp = await client.post(url, auth=self.auth, data=params, timeout=10.0)
                else:
                    url = f"{self.url}/job/{job_name}/build"
                    # Jenkins requires a CSRF crumb for POST — try without first (anonymous config),
                    # then fall back to fetching the crumb
                    crumb = await self._get_crumb(client)
                    headers = {crumb["crumbRequestField"]: crumb["crumb"]} if crumb else {}
                    resp = await client.post(url, auth=self.auth, headers=headers, timeout=10.0)
                resp.raise_for_status()
                return {"triggered": True, "job": job_name, "status_code": resp.status_code}
        except Exception as exc:
            return {"triggered": False, "error": str(exc)}

    async def _get_crumb(self, client: httpx.AsyncClient) -> dict | None:
        """Fetch Jenkins CSRF crumb required for POST requests."""
        try:
            resp = await client.get(
                f"{self.url}/crumbIssuer/api/json",
                auth=self.auth,
                timeout=5.0,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def list_jobs(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.url}/api/json",
                    auth=self.auth,
                    params={"tree": "jobs[name,color,url,lastBuild[number,result,duration,timestamp]]"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                return resp.json().get("jobs", [])
        except Exception as exc:
            return [{"error": str(exc)}]
