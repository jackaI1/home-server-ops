# Jenkins LTS, pinned to one release. Update the tag on purpose, after reading the Jenkins changelog.
FROM jenkins/jenkins:2.479.3-lts-jdk17

# The Docker CLI only: the daemon is the host's, reached through the mounted socket.
COPY --from=docker:27.3.1-cli /usr/local/bin/docker /usr/local/bin/docker

COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
