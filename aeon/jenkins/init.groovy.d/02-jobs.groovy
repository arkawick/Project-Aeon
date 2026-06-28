import jenkins.model.*
import org.jenkinsci.plugins.workflow.job.*
import org.jenkinsci.plugins.workflow.cps.*

def jenkins = Jenkins.getInstance()

def createJob = { String name, String script ->
    if (jenkins.getItem(name) != null) {
        println "[Aeon] Job '${name}' already exists, skipping"
        return
    }
    def job = jenkins.createProject(WorkflowJob, name)
    job.setDescription("Aeon demo pipeline — auto-seeded")
    job.definition = new CpsFlowDefinition(script, true)
    job.save()
    println "[Aeon] Created job: ${name}"
    // Trigger one build immediately so there are logs to analyze
    job.scheduleBuild2(0)
}

// -------------------------------------------------------------------
// Job 1: frontend-build — fails with missing module alias
// -------------------------------------------------------------------
createJob('frontend-build', '''
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                echo "Checking out branch: feature/new-dashboard"
                echo "Commit: a3f9c12"
            }
        }
        stage('Install Dependencies') {
            steps {
                echo "Running: npm ci"
                echo "npm warn deprecated inflight@1.0.6"
                echo "npm warn deprecated glob@7.2.3"
                echo "added 1483 packages in 14.2s"
            }
        }
        stage('Build') {
            steps {
                echo "Running: npm run build"
                echo ""
                echo "  vite v5.1.4 building for production..."
                echo ""
                echo "  transforming..."
                echo "  x Build failed in 1.23s"
                echo ""
                echo "error during build:"
                echo "Error: Cannot find module \'@/components/Button\'"
                echo "    at resolve (/app/node_modules/vite/dist/node/chunks/dep-jDlqpMoJ.js:48773:19)"
                echo "    at resolveId (/app/node_modules/vite/dist/node/chunks/dep-jDlqpMoJ.js:48755:20)"
                echo ""
                echo "  The file \'@/components/Button\' cannot be found."
                echo "  Check that path aliases are configured in vite.config.js:"
                echo "    resolve: { alias: { \'@\': path.resolve(__dirname, \'src\') } }"
                error("Build failed: Module resolution error '@/components/Button'")
            }
        }
    }
    post {
        failure {
            echo "Pipeline FAILED — see build log for details"
        }
    }
}
''')

// -------------------------------------------------------------------
// Job 2: backend-tests — fails with OOM
// -------------------------------------------------------------------
createJob('backend-tests', '''
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                echo "Checking out branch: develop"
                echo "Commit: b7e2d41"
            }
        }
        stage('Unit Tests') {
            steps {
                echo "Running: mvn test -Dsurefire.failIfNoSpecifiedTests=false"
                echo "[INFO] Scanning for projects..."
                echo "[INFO] Building data-service 2.3.1"
                echo "[INFO] Tests run: 142, Failures: 0, Errors: 0, Skipped: 0"
                echo "[INFO] BUILD SUCCESS"
            }
        }
        stage('Integration Tests') {
            steps {
                echo "Running: mvn verify -P integration-tests"
                echo "[INFO] Starting integration test suite..."
                echo "[INFO] Connecting to test database..."
                echo "[INFO] Running: DataServiceIntegrationTest"
                echo "[INFO] Running: ConnectionPoolIntegrationTest"
                echo ""
                echo "[ERROR] Java heap space"
                echo "java.lang.OutOfMemoryError: Java heap space"
                echo "\\tat java.base/java.util.Arrays.copyOf(Arrays.java:3236)"
                echo "\\tat com.acme.dataservice.pool.ConnectionPool.allocate(ConnectionPool.java:87)"
                echo "\\tat com.acme.dataservice.test.ConnectionPoolIntegrationTest.testConcurrentConnections(ConnectionPoolIntegrationTest.java:134)"
                echo ""
                echo "[ERROR] Tests run: 67, Failures: 1, Errors: 2, Skipped: 0"
                echo "[INFO] BUILD FAILURE"
                error("Integration tests failed: OutOfMemoryError in connection pool")
            }
        }
    }
}
''')

// -------------------------------------------------------------------
// Job 3: android-build — fails with Gradle dependency conflict
// -------------------------------------------------------------------
createJob('android-build', '''
pipeline {
    agent any
    stages {
        stage('Checkout') {
            steps {
                echo "Checking out branch: main"
                echo "Commit: c9a1f03"
            }
        }
        stage('Lint') {
            steps {
                echo "Running: ./gradlew lint"
                echo "> Task :app:lint"
                echo "Lint found no issues"
                echo "BUILD SUCCESSFUL in 8s"
            }
        }
        stage('Build APK') {
            steps {
                echo "Running: ./gradlew assembleRelease"
                echo "> Configure project :app"
                echo "> Task :app:preBuild"
                echo "> Task :app:preReleaseBuild"
                echo ""
                echo "FAILURE: Build failed with an exception."
                echo ""
                echo "* What went wrong:"
                echo "Execution failed for task \':app:checkReleaseDuplicateClasses\'."
                echo "> Could not resolve com.google.android.material:material:1.9.0."
                echo "  Dependency resolution failed:"
                echo "  > Module 'androidx.core:core' has been requested with conflicting versions:"
                echo "      - Version 1.12.0 from :app"
                echo "      - Version 1.15.0 from androidx.activity:activity:1.8.2"
                echo ""
                echo "  Fix: Add to build.gradle configurations.all {"
                echo "    resolutionStrategy.force 'androidx.core:core-ktx:1.15.0'"
                echo "  }"
                error("Gradle build failed: androidx.core version conflict")
            }
        }
    }
}
''')

// -------------------------------------------------------------------
// Job 4: docker-image-build — fails with disk full
// -------------------------------------------------------------------
createJob('docker-image-build', '''
pipeline {
    agent any
    environment {
        IMAGE_NAME = 'acme/platform-services'
        REGISTRY   = 'registry.acme.internal'
    }
    stages {
        stage('Checkout') {
            steps {
                echo "Branch: main  Commit: d4e8f21"
            }
        }
        stage('Validate Dockerfile') {
            steps {
                echo "Running hadolint on Dockerfile..."
                echo "Hadolint passed with 0 errors, 2 warnings"
            }
        }
        stage('Build Image') {
            steps {
                echo "Sending build context to Docker daemon  142.3MB"
                echo "Step 1/14 : FROM python:3.11-slim"
                echo " ---> a6d8a6f3e5c2"
                echo "Step 2/14 : WORKDIR /app"
                echo " ---> Using cache"
                echo "Step 4/14 : RUN pip install --no-cache-dir -r requirements.txt"
                echo " ---> Running in 3e5d7f9a1b2c"
                echo ""
                echo "ERROR: failed to solve: write /var/lib/docker/tmp/GetImageBlob: no space left on device"
                error("Docker build failed: no space left on device — run docker system prune -af on the CI runner")
            }
        }
    }
    post {
        failure {
            echo "Fix: ssh into the runner and run: docker system prune -af"
        }
    }
}
''')

// -------------------------------------------------------------------
// Job 5: deploy-staging — succeeds (healthy baseline)
// -------------------------------------------------------------------
createJob('deploy-staging', '''
pipeline {
    agent any
    environment {
        CLUSTER   = 'staging-us-east-1'
        NAMESPACE = 'platform'
        SERVICE   = 'platform-services'
    }
    stages {
        stage('Checkout') {
            steps {
                echo "Branch: main  Commit: d4e8f21"
            }
        }
        stage('Validate Manifests') {
            steps {
                echo "kubeval k8s/staging/*.yaml"
                echo "k8s/staging/deployment.yaml - OK"
                echo "k8s/staging/service.yaml - OK"
                echo "All manifests valid"
            }
        }
        stage('Deploy') {
            steps {
                echo "kubectl set image deployment/${SERVICE} ..."
                echo "Waiting for rollout to finish: 1 of 2 replicas available..."
                echo "deployment '${SERVICE}' successfully rolled out"
            }
        }
        stage('Smoke Tests') {
            steps {
                echo "GET /health         → 200 OK  (12ms)"
                echo "GET /api/v1/status  → 200 OK  (34ms)"
                echo "POST /api/v1/ingest → 202 Accepted  (89ms)"
                echo "All 3 smoke tests passed"
            }
        }
    }
    post {
        success {
            echo "Deployment to staging complete"
        }
    }
}
''')

jenkins.save()
println "[Aeon] All demo jobs created and scheduled"
