# Jenkins for LifeOS

This page has the setup steps for the Jenkins controller and the two LifeOS jobs. The overview is in the README.

## Start the controller

On the home server, from the repository root:

```sh
cp deploy/jenkins/.env.example deploy/jenkins/.env
stat -c '%g' /var/run/docker.sock        # put this number in DOCKER_GID in .env
docker compose -f deploy/jenkins/compose.yml up -d --build --wait
```

The controller is at `http://127.0.0.1:8080`. It is published on loopback only. From a laptop, open a tunnel with `ssh -L 8080:127.0.0.1:8080 <server>` and visit `http://127.0.0.1:8080` there. On the first start, Jenkins prints an admin password in the container log: `docker compose -f deploy/jenkins/compose.yml logs jenkins`.

The image is `jenkins/jenkins:2.541.3-lts-jdk17` with the Docker CLI and the plugins in `plugins.txt` added. To update Jenkins, change the tag in `Dockerfile` and `compose.yml` together, after reading its changelog.

## Create the two jobs

1. **lifeos-build**: New item, Pipeline. Definition "Pipeline script from SCM", Git repository `https://github.com/jackaI1/home-server-ops.git`, branch `main`, Script Path `deploy/jenkins/Jenkinsfile`.
2. **lifeos-deploy**: the same, with Script Path `deploy/jenkins/Jenkinsfile.deploy`.

## Add the LifeOS secrets

In Manage Jenkins, Credentials, add a **Secret file** with ID `lifeos-env-file`. Upload the env file that LifeOS reads. Jenkins stores it encrypted, and the deploy job copies it to `/opt/lifeos/lifeos.env` with mode 600. Nothing secret goes in the repository.

## What runs

- **lifeos-build** checks out `lifeos-open`, runs `npm ci`, `npm run lint`, `npm run typecheck` and the test suite. The test step writes a JUnit report, which Jenkins shows as the test results and archives. It then builds `deploy/jenkins/lifeos.Dockerfile`. When the branch is `main` and everything passed, it starts **lifeos-deploy**.
- **lifeos-deploy** calls `deploy/jenkins/deploy-lifeos.sh`. The script copies the compose file and the env file, starts LifeOS with the new image, and waits for the health check. If the health check fails, it starts the previous image again and the job fails.

## Limits

- The Docker socket is mounted into the controller so builds can run. Anyone who can change a job can run containers as root on the host. Keep the login on and keep the port on loopback.
- LifeOS listens on 127.0.0.1 and uses host networking, so it shares the host's loopback. The health check assumes port 8787.
- The plugin versions are not pinned; the controller image is.
- At the time of writing, two of LifeOS's own demo tests fail on the public `main` branch of `lifeos-open` (`test/demo-assistant.test.mjs` and `test/demo-assistant-actions.test.mjs`). The build job's test stage shows that as a failure until they are fixed there. The CI job reports the count and does not gate on it, so it checks the pipeline's report step rather than LifeOS's tests.

## Tests

`python -m pytest -q deploy/tests/test_jenkins.py` checks the compose file, both Jenkinsfiles, the LifeOS Dockerfile and the deploy script. The script is run against a fake `docker`, so the rollback path is tested without a daemon. CI (`.github/workflows/jenkins.yml`) also starts the controller, runs the same steps as the build pipeline against a public copy of `lifeos-open`, and runs the built image.
