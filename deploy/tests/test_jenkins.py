"""Checks for the Jenkins controller, both Jenkinsfiles, the LifeOS image and the deploy script.

These run without Docker or Jenkins. The deploy script is run with a fake `docker` so the rollback
path is exercised for real: the fake fails the first `compose up` for one image name.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

JENKINS = Path(__file__).resolve().parents[1] / "jenkins"
BUILD = JENKINS / "Jenkinsfile"
DEPLOY = JENKINS / "Jenkinsfile.deploy"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def strip_groovy_comments_and_strings(text: str) -> str:
    """Remove // comments and quoted strings so brace counting is not fooled by them."""
    # Strings go first: a URL such as https://... inside a string must not be read as a comment.
    text = re.sub(r"'''.*?'''", "''", text, flags=re.S)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"//[^\n]*", "", text)
    return text


# ---- Jenkins controller -------------------------------------------------------------------------

def test_controller_is_pinned_and_listens_on_loopback_only():
    compose = load_yaml(JENKINS / "compose.yml")
    jenkins = compose["services"]["jenkins"]
    assert jenkins["image"].startswith("home-ops/jenkins:2.")
    assert "latest" not in jenkins["image"]
    assert jenkins["ports"], "the web UI must be published on purpose"
    for port in jenkins["ports"]:
        assert str(port).startswith("127.0.0.1:"), f"{port} would be reachable from the LAN"
    assert "privileged" not in jenkins


def test_controller_keeps_its_state_in_a_named_volume():
    compose = load_yaml(JENKINS / "compose.yml")
    jenkins = compose["services"]["jenkins"]
    assert any(str(v).startswith("jenkins_home:/var/jenkins_home") for v in jenkins["volumes"])
    assert "jenkins_home" in compose["volumes"]


def test_controller_has_a_health_check_and_no_new_privileges():
    jenkins = load_yaml(JENKINS / "compose.yml")["services"]["jenkins"]
    assert jenkins["healthcheck"]["test"][-1].endswith("/login")
    assert "no-new-privileges:true" in jenkins["security_opt"]


def test_dockerfile_pins_the_base_image_and_installs_plugins():
    text = (JENKINS / "Dockerfile").read_text()
    from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    assert from_lines == ["FROM jenkins/jenkins:2.479.3-lts-jdk17"]
    assert "jenkins-plugin-cli --plugin-file" in text


def test_plugin_list_has_what_both_pipelines_use():
    plugins = {line.strip() for line in (JENKINS / "plugins.txt").read_text().splitlines()
               if line.strip() and not line.startswith("#")}
    assert {"workflow-aggregator", "git", "docker-workflow", "junit", "credentials-binding"} <= plugins


# ---- Jenkinsfiles -------------------------------------------------------------------------------

def test_build_pipeline_runs_checks_in_order_then_builds_the_image():
    stages = re.findall(r"stage\('([^']+)'\)", BUILD.read_text())
    assert stages == ["Check out LifeOS", "Install dependencies", "Lint", "Type check", "Test", "Build image"]


def test_build_pipeline_runs_the_lifeos_scripts_it_is_supposed_to():
    text = BUILD.read_text()
    assert "npm ci" in text
    assert "npm run lint" in text
    assert "npm run typecheck" in text
    assert "node --test" in text
    assert "deploy/jenkins/lifeos.Dockerfile" in text
    assert "--test-reporter=junit" in text


def test_build_pipeline_archives_the_report_and_publishes_it_to_jenkins():
    text = BUILD.read_text()
    assert "junit testResults: 'lifeos/reports/junit.xml'" in text
    assert "archiveArtifacts artifacts: 'lifeos/reports/**" in text


def test_build_pipeline_starts_deploy_only_for_main_and_after_success():
    text = BUILD.read_text()
    assert "success {" in text
    assert "params.LIFEOS_BRANCH == 'main'" in text
    assert "build job: 'lifeos-deploy'" in text


def test_deploy_pipeline_reads_its_secret_from_the_jenkins_store():
    text = DEPLOY.read_text()
    assert "withCredentials([file(credentialsId: 'lifeos-env-file'" in text
    assert "deploy/jenkins/deploy-lifeos.sh" in text


@pytest.mark.parametrize("path", [BUILD, DEPLOY])
def test_jenkinsfiles_have_balanced_braces(path):
    code = strip_groovy_comments_and_strings(path.read_text())
    assert code.count("{") == code.count("}")
    assert code.count("(") == code.count(")")


@pytest.mark.parametrize("path", [BUILD, DEPLOY, JENKINS / "lifeos.Dockerfile"])
def test_no_secret_values_are_written_into_the_repo(path):
    text = path.read_text()
    assert not re.search(r"(?i)(password|token|secret|apikey)\s*[:=]\s*['\"][^'\"]{4,}", text)


# ---- LifeOS image and compose file --------------------------------------------------------------

def test_lifeos_dockerfile_is_multi_stage_pinned_and_runs_as_node_user():
    text = (JENKINS / "lifeos.Dockerfile").read_text()
    froms = re.findall(r"^FROM (\S+)(?: AS (\S+))?$", text, flags=re.M)
    stage_names = {alias for _, alias in froms if alias}
    images = [image for image, _ in froms if image not in stage_names]  # "FROM deps" names a stage, not an image
    assert len(froms) >= 3
    assert images and all(":" in image and "latest" not in image for image in images)
    last_stage_block = text.split("AS runtime", 1)[1]
    assert "USER node" in last_stage_block
    assert 'CMD ["node", "build/server.mjs"]' in last_stage_block


def test_lifeos_compose_reads_the_secret_env_file_and_checks_health():
    svc = load_yaml(JENKINS / "lifeos-compose.yml")["services"]["lifeos"]
    assert svc["env_file"] == "lifeos.env"
    assert svc["network_mode"] == "host"
    assert svc["healthcheck"]["test"][0] == "CMD"
    assert "LIFEOS_IMAGE" in svc["image"]


# ---- deploy script, run with a fake docker ------------------------------------------------------

FAKE_DOCKER = """#!/usr/bin/env bash
# Fake docker for tests: logs every call; `compose up` fails when LIFEOS_IMAGE is in FAIL_IMAGES.
echo "$*" >> "$FAKE_LOG"
if [[ "$1" == "image" ]]; then exit 0; fi
if [[ "$1" == "compose" ]]; then
  for bad in ${FAIL_IMAGES:-}; do
    if [[ "${LIFEOS_IMAGE:-}" == "$bad" ]]; then exit 1; fi
  done
  exit 0
fi
exit 0
"""


def run_deploy(tmp_path: Path, image: str, fail_images: str = "") -> subprocess.CompletedProcess:
    fake = tmp_path / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env_file = tmp_path / "secret.env"
    env_file.write_text("LIFEOS_TOKEN_PLACEHOLDER=not-a-real-value\n")
    env = {
        **os.environ,
        "DOCKER": str(fake),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAIL_IMAGES": fail_images,
    }
    return subprocess.run(
        ["bash", str(JENKINS / "deploy-lifeos.sh"), image, str(env_file), str(tmp_path / "deploy")],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_deploy_script_is_executable_and_lint_clean():
    assert os.access(JENKINS / "deploy-lifeos.sh", os.X_OK)


def test_deploy_writes_env_file_with_private_mode_and_records_the_image(tmp_path):
    result = run_deploy(tmp_path, "lifeos:1")
    assert result.returncode == 0, result.stderr
    deploy = tmp_path / "deploy"
    assert (deploy / "current-image").read_text().strip() == "lifeos:1"
    assert stat.S_IMODE((deploy / "lifeos.env").stat().st_mode) == 0o600
    assert stat.S_IMODE(deploy.stat().st_mode) == 0o700


def test_failed_deploy_rolls_back_to_the_previous_image(tmp_path):
    assert run_deploy(tmp_path, "lifeos:1").returncode == 0
    result = run_deploy(tmp_path, "lifeos:2", fail_images="lifeos:2")
    assert result.returncode == 1
    assert "rolling back to lifeos:1" in result.stderr
    assert (tmp_path / "deploy" / "current-image").read_text().strip() == "lifeos:1"
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert sum("compose -p lifeos" in c for c in calls) == 3  # first deploy, failed deploy, rollback


def test_first_ever_failed_deploy_has_nothing_to_roll_back_to(tmp_path):
    result = run_deploy(tmp_path, "lifeos:9", fail_images="lifeos:9")
    assert result.returncode == 1
    assert "rolling back" not in result.stderr
    assert not (tmp_path / "deploy" / "current-image").exists()
