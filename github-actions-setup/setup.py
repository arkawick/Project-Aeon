#!/usr/bin/env python3
"""
Aeon — GitHub Actions Real Integration Setup
=============================================
Does everything in one command:
  1. Starts a localtunnel to expose Aeon (localhost:8000) publicly
  2. Creates a GitHub repo (or uses existing)
  3. Encrypts + uploads AEON_URL as a repo secret
  4. Pushes all 5 workflow files to .github/workflows/
  5. Triggers an initial workflow run

Prerequisites:
  pip install requests PyNaCl
  Node.js installed (for npx localtunnel)

Usage:
  python setup.py --token ghp_xxx --repo aeon-demo
  python setup.py --token ghp_xxx --repo my-org/aeon-demo   # existing repo
  python setup.py --token ghp_xxx --repo aeon-demo --skip-tunnel  # if tunnel already running
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path

import requests

try:
    from nacl import encoding, public as nacl_public
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

WORKFLOWS_DIR = Path(__file__).parent / "workflows"
WORKFLOW_FILES = [
    "frontend-build.yml",
    "backend-tests.yml",
    "android-build.yml",
    "docker-image-build.yml",
    "deploy-staging.yml",
]

GH_API = "https://api.github.com"


# ── GitHub API helpers ────────────────────────────────────────────────────────

def gh(method: str, path: str, token: str, **kwargs):
    url = f"{GH_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **kwargs.pop("headers", {}),
    }
    r = requests.request(method, url, headers=headers, timeout=15, **kwargs)
    return r


def get_user(token: str) -> str:
    r = gh("GET", "/user", token)
    r.raise_for_status()
    return r.json()["login"]


def repo_exists(owner: str, repo: str, token: str) -> bool:
    r = gh("GET", f"/repos/{owner}/{repo}", token)
    return r.status_code == 200


def create_repo(owner: str, repo: str, token: str, is_org: bool) -> dict:
    payload = {
        "name": repo,
        "description": "Aeon CI/CD demo — GitHub Actions integration",
        "private": False,
        "auto_init": True,
    }
    path = f"/orgs/{owner}/repos" if is_org else "/user/repos"
    r = gh("POST", path, token, json=payload)
    r.raise_for_status()
    return r.json()


def get_repo_public_key(owner: str, repo: str, token: str) -> dict:
    r = gh("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key", token)
    r.raise_for_status()
    return r.json()


def encrypt_secret(public_key_b64: str, secret: str) -> str:
    if not HAS_NACL:
        raise RuntimeError("PyNaCl not installed. Run: pip install PyNaCl")
    pk_bytes = base64.b64decode(public_key_b64)
    box = nacl_public.SealedBox(nacl_public.PublicKey(pk_bytes))
    encrypted = box.encrypt(secret.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def set_secret(owner: str, repo: str, token: str, name: str, value: str):
    pk = get_repo_public_key(owner, repo, token)
    encrypted = encrypt_secret(pk["key"], value)
    r = gh(
        "PUT",
        f"/repos/{owner}/{repo}/actions/secrets/{name}",
        token,
        json={"encrypted_value": encrypted, "key_id": pk["key_id"]},
    )
    r.raise_for_status()


def push_file(owner: str, repo: str, token: str, path: str, content: str, message: str):
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    # Check if file exists (need SHA for update)
    r = gh("GET", f"/repos/{owner}/{repo}/contents/{path}", token)
    payload = {"message": message, "content": encoded}
    if r.status_code == 200:
        payload["sha"] = r.json()["sha"]
    r = gh("PUT", f"/repos/{owner}/{repo}/contents/{path}", token, json=payload)
    r.raise_for_status()


def trigger_workflow(owner: str, repo: str, token: str, workflow_file: str):
    r = gh(
        "POST",
        f"/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
        token,
        json={"ref": "main"},
    )
    return r.status_code == 204


# ── localtunnel ───────────────────────────────────────────────────────────────

def start_localtunnel(port: int = 8000, subdomain: str = "aeon-demo") -> str:
    """Start localtunnel via npx and return the public URL."""
    print(f"  Starting localtunnel (subdomain: {subdomain})...")

    cmd = f"npx --yes localtunnel --port {port} --subdomain {subdomain}"
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=True,
    )

    # Read stdout until we see the URL
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        match = re.search(r"https://[^\s]+\.loca\.lt", line)
        if match:
            url = match.group(0)
            break

    if not url:
        proc.terminate()
        raise RuntimeError("localtunnel did not produce a URL within 30s. Is Node.js installed?")

    # Keep the process alive in a background thread
    def drain():
        for _ in proc.stdout:
            pass
    threading.Thread(target=drain, daemon=True).start()

    return url, proc


def verify_tunnel(url: str) -> bool:
    """Check that the tunnel actually reaches Aeon."""
    try:
        r = requests.get(
            f"{url}/health",
            headers={"bypass-tunnel-reminder": "true"},
            timeout=10,
        )
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Aeon GitHub Actions setup")
    parser.add_argument("--token",        required=True,  help="GitHub Personal Access Token (scopes: repo, workflow)")
    parser.add_argument("--repo",         required=True,  help="Repo name (e.g. 'aeon-demo') or 'org/aeon-demo'")
    parser.add_argument("--port",         default=8000,   type=int, help="Aeon backend port (default: 8000)")
    parser.add_argument("--subdomain",    default="aeon-demo", help="localtunnel subdomain (default: aeon-demo)")
    parser.add_argument("--tunnel-url",   default=None,   help="Skip localtunnel and use this URL directly")
    parser.add_argument("--skip-trigger", action="store_true", help="Don't trigger workflow runs after setup")
    args = parser.parse_args()

    # ── Resolve owner/repo ────────────────────────────────────────────────────
    if "/" in args.repo:
        owner, repo_name = args.repo.split("/", 1)
        is_org = True
    else:
        print("Fetching GitHub user...")
        owner = get_user(args.token)
        repo_name = args.repo
        is_org = False

    print(f"\n{'='*55}")
    print(f"  Aeon GitHub Actions Setup")
    print(f"{'='*55}")
    print(f"  Repo:  {owner}/{repo_name}")
    print(f"  Port:  {args.port}")
    print()

    # ── Step 1: localtunnel ───────────────────────────────────────────────────
    tunnel_proc = None
    if args.tunnel_url:
        aeon_url = args.tunnel_url.rstrip("/")
        print(f"[1/4] Using provided tunnel URL: {aeon_url}")
    else:
        print("[1/4] Starting localtunnel...")
        try:
            aeon_url, tunnel_proc = start_localtunnel(args.port, args.subdomain)
            print(f"       Tunnel URL: {aeon_url}")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    print("       Verifying Aeon is reachable...")
    for attempt in range(1, 6):
        if verify_tunnel(aeon_url):
            print(f"       Aeon is reachable via tunnel")
            break
        print(f"       Attempt {attempt}/5 — retrying in 3s...")
        time.sleep(3)
    else:
        print("  WARNING: Could not reach Aeon through the tunnel.")
        print("           Make sure 'docker compose up -d' is running.")
        print("           Continuing anyway — secret will still be set.")

    # ── Step 2: Create repo ───────────────────────────────────────────────────
    print(f"\n[2/4] Setting up GitHub repo: {owner}/{repo_name}")
    if repo_exists(owner, repo_name, args.token):
        print(f"       Repo already exists — using it")
    else:
        print(f"       Creating new repo...")
        create_repo(owner, repo_name, args.token, is_org)
        print(f"       Created: https://github.com/{owner}/{repo_name}")
        time.sleep(2)  # give GitHub a moment

    # ── Step 3: Set AEON_URL secret ───────────────────────────────────────────
    print(f"\n[3/4] Setting AEON_URL secret...")
    if not HAS_NACL:
        print("  ERROR: PyNaCl is required to encrypt GitHub secrets.")
        print("         Run: pip install PyNaCl")
        sys.exit(1)
    set_secret(owner, repo_name, args.token, "AEON_URL", aeon_url)
    print(f"       AEON_URL = {aeon_url}")

    # ── Step 4: Push workflow files ───────────────────────────────────────────
    print(f"\n[4/4] Pushing workflow files to .github/workflows/...")
    for filename in WORKFLOW_FILES:
        fpath = WORKFLOWS_DIR / filename
        if not fpath.exists():
            print(f"       SKIP  {filename} (file not found)")
            continue
        content = fpath.read_text(encoding="utf-8")
        push_file(
            owner, repo_name, args.token,
            path=f".github/workflows/{filename}",
            content=content,
            message=f"ci: add {filename} workflow",
        )
        print(f"       pushed  {filename}")

    # ── Step 5: Trigger runs ──────────────────────────────────────────────────
    if not args.skip_trigger:
        print(f"\nTriggering initial workflow runs...")
        time.sleep(2)
        for filename in WORKFLOW_FILES:
            ok = trigger_workflow(owner, repo_name, args.token, filename)
            status = "triggered" if ok else "skipped (workflow_dispatch not enabled yet)"
            print(f"       {filename}: {status}")

    # ── Done ──────────────────────────────────────────────────────────────────
    print(f"""
{'='*55}
  Setup complete!

  GitHub repo:   https://github.com/{owner}/{repo_name}
  Actions tab:   https://github.com/{owner}/{repo_name}/actions
  Aeon tunnel:   {aeon_url}

  Workflow runs will appear in Aeon → Pipelines within
  seconds of each GitHub Actions job completing.

  IMPORTANT: Keep this terminal open while testing.
             Closing it stops the localtunnel.
{'='*55}
""")

    if tunnel_proc:
        print("Tunnel is running. Press Ctrl+C to stop.")
        try:
            tunnel_proc.wait()
        except KeyboardInterrupt:
            tunnel_proc.terminate()
            print("\nTunnel stopped.")


if __name__ == "__main__":
    main()
