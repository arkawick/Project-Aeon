/**
 * Jenkins Job DSL Seed Script
 *
 * Creates all 5 Aeon demo pipeline jobs from the Jenkinsfiles in this repo.
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
    [name: 'frontend-build',    file: 'Jenkinsfile.frontend', desc: 'Vite/React build — fails: missing path alias'],
    [name: 'backend-tests',     file: 'Jenkinsfile.backend',  desc: 'Maven integration tests — fails: OutOfMemoryError'],
    [name: 'android-build',     file: 'Jenkinsfile.android',  desc: 'Gradle APK — fails: androidx.core version conflict'],
    [name: 'docker-image-build',file: 'Jenkinsfile.docker',   desc: 'Docker build — fails: no space left on device'],
    [name: 'deploy-staging',    file: 'Jenkinsfile.deploy',   desc: 'Staging deploy — succeeds (healthy baseline)'],
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
