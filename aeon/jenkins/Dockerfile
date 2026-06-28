FROM jenkins/jenkins:lts-jdk17

# Skip the setup wizard so it boots straight into a usable instance
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"

# Pre-install the Pipeline plugin suite and git
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Seed admin user + demo jobs on first boot
COPY init.groovy.d/ /usr/share/jenkins/ref/init.groovy.d/
