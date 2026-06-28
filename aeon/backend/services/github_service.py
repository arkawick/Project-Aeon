import os
import httpx
from typing import Any


class GitHubService:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.org = os.getenv("GITHUB_ORG", "")
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._login: str | None = None  # resolved lazily on first call

    async def _owner(self) -> str:
        """Return org name if set; otherwise resolve the authenticated user's login."""
        if self.org:
            return self.org
        if self._login:
            return self._login
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/user", headers=self.headers, timeout=5.0
                )
                if resp.status_code == 200:
                    self._login = resp.json().get("login", "")
                    return self._login
        except Exception:
            pass
        return ""

    async def check_connectivity(self) -> bool:
        if not self.token:
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/rate_limit", headers=self.headers, timeout=5.0
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def get_repos(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient() as client:
                url = (
                    f"{self.base_url}/orgs/{self.org}/repos"
                    if self.org
                    else f"{self.base_url}/user/repos"
                )
                resp = await client.get(
                    url, headers=self.headers, params={"per_page": 30}, timeout=10.0
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return [{"error": str(exc)}]

    async def get_workflow_runs(self, repo: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            owner = await self._owner()
            if not owner:
                return [{"error": "Could not resolve GitHub owner"}]
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{owner}/{repo}/actions/runs"
                resp = await client.get(
                    url, headers=self.headers, params={"per_page": limit}, timeout=10.0
                )
                resp.raise_for_status()
                return resp.json().get("workflow_runs", [])
        except Exception as exc:
            return [{"error": str(exc)}]

    async def get_run_logs(self, repo: str, run_id: str) -> dict[str, Any]:
        """
        Fetch logs for all jobs in a workflow run as plain text.
        GitHub's /logs endpoint returns a redirect to a zip — we use
        /jobs instead to get per-job plain-text logs.
        """
        try:
            owner = await self._owner()
            if not owner:
                return {"error": "Could not resolve GitHub owner", "logs": ""}
            async with httpx.AsyncClient(follow_redirects=True) as client:
                jobs_url = f"{self.base_url}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
                jobs_resp = await client.get(jobs_url, headers=self.headers, timeout=10.0)
                jobs_resp.raise_for_status()
                jobs = jobs_resp.json().get("jobs", [])

                all_logs: list[str] = []
                for job in jobs[:5]:
                    job_id = job.get("id")
                    job_name = job.get("name", "job")
                    all_logs.append(f"\n=== Job: {job_name} ===")
                    for step in job.get("steps", []):
                        status = step.get("conclusion") or step.get("status", "?")
                        all_logs.append(f"  [{status}] {step.get('name', '')}")

                    log_url = f"{self.base_url}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"
                    log_resp = await client.get(
                        log_url,
                        headers={**self.headers, "Accept": "application/vnd.github.v3.raw"},
                        timeout=15.0,
                    )
                    if log_resp.status_code == 200:
                        all_logs.append(log_resp.text[:5000])

                return {"logs": "\n".join(all_logs), "run_id": run_id, "job_count": len(jobs)}
        except Exception as exc:
            return {"error": str(exc), "logs": ""}

    async def create_issue(
        self, repo: str, title: str, body: str, labels: list[str] = []
    ) -> dict[str, Any]:
        try:
            owner = await self._owner()
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{owner}/{repo}/issues"
                payload: dict[str, Any] = {"title": title, "body": body}
                if labels:
                    payload["labels"] = labels
                resp = await client.post(url, headers=self.headers, json=payload, timeout=10.0)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"error": str(exc), "created": False}

    async def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict[str, Any]:
        try:
            owner = await self._owner()
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
                payload = {
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                }
                resp = await client.post(url, headers=self.headers, json=payload, timeout=10.0)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"error": str(exc), "created": False}
