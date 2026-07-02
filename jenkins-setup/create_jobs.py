#!/usr/bin/env python3
"""
Aeon Jenkins Job Seeder
=======================
Creates all 10 demo pipeline jobs in Jenkins via the REST API.
No plugins needed beyond what the Aeon Dockerfile already installs.

Usage:
    pip install requests
    python create_jobs.py --token YOUR_API_TOKEN
    python create_jobs.py --url http://localhost:8088 --user admin --token YOUR_API_TOKEN

To generate a token:
    Jenkins → click your username (top-right) → Configure → API Token → Add new Token
"""

import argparse
import getpass
import os
import sys
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth

parser = argparse.ArgumentParser(description="Seed Aeon demo jobs into Jenkins")
parser.add_argument("--url",      default=os.getenv("JENKINS_URL",   "http://localhost:8088"), help="Jenkins base URL")
parser.add_argument("--user",     default=os.getenv("JENKINS_USER",  "admin"),                 help="Jenkins username")
parser.add_argument("--token",    default=os.getenv("JENKINS_TOKEN", ""),                      help="Jenkins API token (prompted if omitted)")
parser.add_argument("--aeon-url", default=os.getenv("AEON_URL",      "http://localhost:8000"), help="Aeon backend URL stored as credential")
args = parser.parse_args()

if not args.token:
    args.token = getpass.getpass(f"Jenkins API token for '{args.user}': ")

JENKINS_URL   = args.url.rstrip("/")
JENKINS_USER  = args.user
JENKINS_TOKEN = args.token
AEON_URL      = args.aeon_url

JOBS_DIR = Path(__file__).parent / "jobs"

JOBS = [
    {
        "name":        "frontend-build",
        "description": "Vite/React build — fails: missing @/components path alias in vite.config.js",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.frontend",
    },
    {
        "name":        "backend-tests",
        "description": "Maven integration tests — fails: OutOfMemoryError in connection pool",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.backend",
    },
    {
        "name":        "android-build",
        "description": "Gradle APK — fails: androidx.core version conflict (1.12.0 vs 1.15.0)",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.android",
    },
    {
        "name":        "docker-image-build",
        "description": "Docker build — fails: no space left on device (CI runner disk full)",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.docker",
    },
    {
        "name":        "deploy-staging",
        "description": "Staging deploy to Kubernetes — succeeds (healthy baseline pipeline)",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.deploy",
    },
    {
        "name":        "security-scan",
        "description": "OWASP + Trivy scan — fails: CRITICAL CVE-2024-0727 in libssl3",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.security-scan",
    },
    {
        "name":        "integration-tests",
        "description": "Playwright E2E — fails: login session cookie regression on auth-refactor",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.integration-tests",
    },
    {
        "name":        "performance-test",
        "description": "k6 load test — fails: p95 latency 847ms exceeds 500ms SLA threshold",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.performance-test",
    },
    {
        "name":        "ios-build",
        "description": "Xcode/Swift build — fails: firebase-ios-sdk SPM version conflict",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.ios-build",
    },
    {
        "name":        "release",
        "description": "Release pipeline — succeeds: builds, tags, and pushes v2.4.1 to registry",
        "jenkinsfile": JOBS_DIR / "Jenkinsfile.release",
    },
]

auth = HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN)


def pipeline_xml(description: str, script: str) -> str:
    """Build a minimal Jenkins Pipeline job config XML."""
    return f"""<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>{description}</description>
  <keepDependencies>false</keepDependencies>
  <properties/>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>{script}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>"""


def get_crumb() -> dict:
    """Fetch Jenkins CSRF crumb."""
    r = requests.get(
        f"{JENKINS_URL}/crumbIssuer/api/json",
        auth=auth,
        timeout=10,
    )
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    return {data["crumbRequestField"]: data["crumb"]}


def job_exists(name: str) -> bool:
    r = requests.get(
        f"{JENKINS_URL}/job/{name}/api/json",
        auth=auth,
        timeout=10,
    )
    return r.status_code == 200


def create_job(name: str, xml: str, crumb: dict) -> bool:
    r = requests.post(
        f"{JENKINS_URL}/createItem?name={name}",
        auth=auth,
        headers={"Content-Type": "application/xml", **crumb},
        data=xml.encode("utf-8"),
        timeout=15,
    )
    return r.status_code in (200, 201)


def update_job(name: str, xml: str, crumb: dict) -> bool:
    r = requests.post(
        f"{JENKINS_URL}/job/{name}/config.xml",
        auth=auth,
        headers={"Content-Type": "application/xml", **crumb},
        data=xml.encode("utf-8"),
        timeout=15,
    )
    return r.status_code == 200


def trigger_build(name: str, crumb: dict) -> bool:
    r = requests.post(
        f"{JENKINS_URL}/job/{name}/build",
        auth=auth,
        headers=crumb,
        timeout=10,
    )
    return r.status_code in (200, 201)


def create_aeon_credential(crumb: dict):
    """Create the AEON_URL secret-text credential if it doesn't exist."""
    cred_xml = f"""<org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl plugin="plain-credentials">
  <scope>GLOBAL</scope>
  <id>AEON_URL</id>
  <description>Aeon backend base URL</description>
  <secret>{AEON_URL}</secret>
</org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl>"""

    r = requests.post(
        f"{JENKINS_URL}/credentials/store/system/domain/_/createCredentials",
        auth=auth,
        headers={"Content-Type": "application/xml", **crumb},
        data=cred_xml.encode("utf-8"),
        timeout=10,
    )
    if r.status_code in (200, 201):
        print("  [+] Created credential: AEON_URL")
    elif r.status_code == 409:
        print("  [~] Credential AEON_URL already exists")
    else:
        print(f"  [!] Credential creation returned {r.status_code} (may already exist)")


def main():
    print(f"Connecting to Jenkins at {JENKINS_URL} ...")

    # Verify connectivity
    try:
        r = requests.get(f"{JENKINS_URL}/api/json", auth=auth, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"ERROR: Cannot reach Jenkins — {e}")
        print(f"       Make sure Jenkins is running at {JENKINS_URL}")
        sys.exit(1)

    print(f"Connected. Jenkins version: {r.headers.get('X-Jenkins', 'unknown')}\n")

    crumb = get_crumb()

    # Set up the AEON_URL credential
    print("Setting up credentials...")
    create_aeon_credential(crumb)
    print()

    # Create / update each job
    for job in JOBS:
        name = job["name"]
        script = job["jenkinsfile"].read_text(encoding="utf-8")
        xml = pipeline_xml(job["description"], script)

        if job_exists(name):
            ok = update_job(name, xml, crumb)
            status = "updated" if ok else "FAILED to update"
        else:
            ok = create_job(name, xml, crumb)
            status = "created" if ok else "FAILED to create"

        print(f"  [{'+' if ok else '!'}] {name}  — {status}")

        if ok:
            built = trigger_build(name, crumb)
            if built:
                print(f"       triggered build #1")

    print(f"\nDone. Open {JENKINS_URL} to see the jobs.")


if __name__ == "__main__":
    main()
