# Jenkins Setup for Aeon

Jenkins runs in Docker as part of the Aeon stack. It starts pre-configured with 5 demo pipeline jobs that automatically notify Aeon on every build.

---

## Accessing Jenkins

**URL:** http://localhost:8088
**Username:** `admin`
**Password:** `admin`

> Port is 8088 (not 8080) — port 8080 is blocked by a WSL/Tomcat process on this machine.

Start Jenkins (along with everything else):
```powershell
cd aeon
docker compose up -d
```

---

## Pre-loaded jobs

Jenkins boots with 5 pipeline jobs seeded automatically by `aeon/jenkins/init.groovy.d/02-jobs.groovy`:

| Job | Simulates | Result |
|---|---|---|
| `frontend-build` | Node.js/Vite build | Fails — missing `@/components/Button` path alias |
| `backend-tests` | Maven integration tests | Fails — `OutOfMemoryError: Java heap space` |
| `android-build` | Gradle APK build | Fails — `androidx.core` version conflict |
| `docker-image-build` | Docker image build | Fails — no space left on device |
| `deploy-staging` | Kubernetes staging deploy | Passes — healthy baseline |

Each job runs once immediately on first boot and notifies Aeon via `POST /api/pipelines/ingest`.

---

## Seeding jobs via Python script

If you need to recreate jobs (e.g. after `docker compose down -v`), use the Python seeder:

```powershell
pip install requests
python jenkins-setup/create_jobs.py
```

Options:
```powershell
# Custom host/credentials
$env:JENKINS_URL = "http://localhost:8088"
$env:JENKINS_USER = "admin"
$env:JENKINS_TOKEN = "admin"
$env:AEON_URL = "http://localhost:8000"
python jenkins-setup/create_jobs.py
```

The script:
1. Creates/updates all 5 jobs via Jenkins REST API (no Job DSL plugin needed)
2. Creates the `AEON_URL` Jenkins credential automatically
3. Triggers build #1 for each job

---

## Job DSL seed script

If you have the Job DSL plugin installed, `seed-jobs.groovy` creates all 5 jobs from Jenkinsfiles in a SCM repo:

1. Update `REPO_URL` in `seed-jobs.groovy` with your repo URL
2. New Item → Freestyle → Build → Process Job DSLs → paste `seed-jobs.groovy`
3. Build now

---

## Jenkinsfile templates

The `jobs/` folder contains full Jenkinsfiles for each pipeline. All include:
- Realistic build stages with real-looking log output
- An `aeon_notify()` function that POSTs to Aeon on success and failure
- The `AEON_URL` Jenkins credential for the Aeon backend URL

| File | Pipeline type |
|---|---|
| `jobs/Jenkinsfile.frontend` | Node.js + Vite |
| `jobs/Jenkinsfile.backend` | Maven + Spring Boot |
| `jobs/Jenkinsfile.android` | Gradle + Android SDK |
| `jobs/Jenkinsfile.docker` | Docker image build |
| `jobs/Jenkinsfile.deploy` | Kubernetes deployment |

---

## Adding Aeon notification to your own Jenkinsfile

```groovy
def aeon_notify(String status, String errorSummary = '', String logs = '') {
    withCredentials([string(credentialsId: 'AEON_URL', variable: 'AEON')]) {
        def payload = """{
            "source": "jenkins",
            "name": "${env.JOB_NAME}",
            "status": "${status}",
            "repo": "your-org/your-repo",
            "branch": "${env.GIT_BRANCH ?: 'main'}",
            "build_number": ${env.BUILD_NUMBER},
            "url": "${env.BUILD_URL}",
            "error_summary": "${errorSummary.replace('"', '\\"')}",
            "logs": "${logs.take(4000).replace('"', '\\"').replace('\n', '\\n')}"
        }"""
        try {
            httpRequest(url: "${AEON}/api/pipelines/ingest", httpMode: 'POST',
                        contentType: 'APPLICATION_JSON', requestBody: payload,
                        timeout: 10, validResponseCodes: '100:299')
        } catch (Exception e) {
            echo "Aeon notification failed (non-critical): ${e.message}"
        }
    }
}

// In your pipeline's post block:
post {
    success { aeon_notify('success') }
    failure { aeon_notify('failure', 'Build failed — check console output') }
}
```

The `AEON_URL` credential must be set to `http://host.docker.internal:8000` when Jenkins and Aeon both run in Docker on the same machine (use `host.docker.internal` so Jenkins can reach the Aeon container via the host).

---

## Verifying the connection

```powershell
# Simulate a Jenkins failure event hitting Aeon
Invoke-RestMethod -Uri http://localhost:8000/api/pipelines/ingest -Method Post `
  -ContentType "application/json" `
  -Body '{"source":"jenkins","name":"test-job","status":"failure","repo":"acme/test","branch":"main","build_number":1,"error_summary":"Test failure"}'
```

Then open http://localhost:3000/pipelines — the event appears immediately.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Jenkins not loading | Use http://localhost:8088 (not 8080) |
| Jobs not appearing | Wait 60s after `docker compose up` — Jenkins takes time to boot |
| Jobs already exist on re-seed | The groovy script skips existing jobs — run `create_jobs.py` instead (it updates) |
| `httpRequest` step not found | Install the **HTTP Request** plugin in Jenkins |
| Jenkins jobs not notifying Aeon | Check the `AEON_URL` credential is set to `http://host.docker.internal:8000` |
| Pipelines page still empty after jobs run | Run `docker compose up -d --force-recreate frontend` |
