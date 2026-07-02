/**
 * Jenkins Job DSL Seed Script
 *
 * Creates all 10 Aeon demo pipeline jobs from the Jenkinsfiles in this repo.
 * Run this once as a Freestyle job with the "Process Job DSLs" build step.
 *
 * Prerequisites:
 *   - Job DSL plugin installed
 *   - Your repo checked out at a known SCM URL
 *
 * Usage:
 *   New Item → Freestyle → Build → Process Job DSLs → Paste this file
 */

def REPO_URL   = 'https://github.com/YOUR_ORG/YOUR_REPO.git'  // ← change this
def REPO_CRED  = 'github-credentials'  // Jenkins credential ID with repo access
def SETUP_PATH = 'jenkins-setup/jobs'  // path inside the repo

[
    [name: 'frontend-build',    file: 'Jenkinsfile.frontend',          desc: 'Vite/React build — fails: missing path alias'],
    [name: 'backend-tests',     file: 'Jenkinsfile.backend',           desc: 'Maven integration tests — fails: OutOfMemoryError'],
    [name: 'android-build',     file: 'Jenkinsfile.android',           desc: 'Gradle APK — fails: androidx.core version conflict'],
    [name: 'docker-image-build',file: 'Jenkinsfile.docker',            desc: 'Docker build — fails: no space left on device'],
    [name: 'deploy-staging',    file: 'Jenkinsfile.deploy',            desc: 'Staging deploy — succeeds (healthy baseline)'],
    [name: 'security-scan',     file: 'Jenkinsfile.security-scan',     desc: 'OWASP + Trivy — fails: CRITICAL CVE-2024-0727 in libssl3'],
    [name: 'integration-tests', file: 'Jenkinsfile.integration-tests', desc: 'Playwright E2E — fails: session cookie regression'],
    [name: 'performance-test',  file: 'Jenkinsfile.performance-test',  desc: 'k6 load test — fails: p95 847ms exceeds 500ms SLA'],
    [name: 'ios-build',         file: 'Jenkinsfile.ios-build',         desc: 'Xcode/Swift — fails: firebase-ios-sdk SPM conflict'],
    [name: 'release',           file: 'Jenkinsfile.release',           desc: 'Release pipeline — succeeds: v2.4.1 to registry'],
].each { job ->
    pipelineJob(job.name) {
        description(job.desc)
        definition {
            cpsScm {
                scm {
                    git {
                        remote {
                            url(REPO_URL)
                            credentials(REPO_CRED)
                        }
                        branch('*/main')
                    }
                }
                scriptPath("${SETUP_PATH}/${job.file}")
            }
        }
        logRotator {
            numToKeep(20)
        }
        triggers {
            scm('H/5 * * * *')
        }
    }
    println "Created job: ${job.name}"
}
