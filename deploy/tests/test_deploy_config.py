"""Checks the Compose stack, the Caddy config, the systemd units and the provisioning script.
These run on any machine. CI also runs `docker compose config` and `shellcheck` on the same files."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((DEPLOY / "compose" / "compose.yml").read_text())
SERVICES = COMPOSE["services"]


def test_every_service_restarts_unless_stopped():
    for name, svc in SERVICES.items():
        assert svc.get("restart") == "unless-stopped", name


def test_images_are_pinned_to_a_version_not_latest():
    for name, svc in SERVICES.items():
        image = svc["image"]
        assert ":" in image and not image.endswith(":latest"), f"{name} image must be pinned: {image}"


def test_only_caddy_publishes_ports_to_the_network():
    published = {name: svc.get("ports", []) for name, svc in SERVICES.items()}
    assert published["caddy"] == ["80:80", "443:443"]
    assert published["app"] == []
    assert SERVICES["app"]["expose"] == ["80"]


def test_app_runs_read_only_with_no_extra_capabilities():
    app = SERVICES["app"]
    assert app["read_only"] is True
    assert app["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in app["security_opt"]


def test_caddy_has_a_health_check_and_only_the_port_it_needs():
    caddy = SERVICES["caddy"]
    assert caddy["healthcheck"]["test"][0] == "CMD"
    assert caddy["cap_drop"] == ["ALL"] and caddy["cap_add"] == ["NET_BIND_SERVICE"]


def test_domain_and_email_come_from_the_env_file_and_must_be_set():
    env = SERVICES["caddy"]["environment"]
    assert env["DOMAIN"].startswith("${DOMAIN:?")
    assert env["ACME_EMAIL"].startswith("${ACME_EMAIL:?")


def test_caddyfile_proxies_to_the_app_and_uses_the_domain_variable():
    text = (DEPLOY / "compose" / "Caddyfile").read_text()
    assert "{$DOMAIN}" in text
    assert "reverse_proxy app:80" in text
    assert "{$ACME_EMAIL}" in text


def test_env_example_has_placeholders_only():
    text = (DEPLOY / "compose" / ".env.example").read_text()
    assert "DOMAIN=home.example.com" in text and "ACME_EMAIL=you@example.com" in text


def test_health_env_example_has_every_setting_the_checker_reads():
    text = (DEPLOY / "vm" / "health.env.example").read_text()
    for key in ("HEALTH_URLS=", "HEALTH_TLS=", "HEALTH_WARN_DAYS=", "ALERT_WEBHOOK="):
        assert key in text


def test_systemd_service_reads_the_env_file_and_runs_the_checker():
    unit = (DEPLOY / "vm" / "systemd" / "home-ops-health.service").read_text()
    assert "EnvironmentFile=/etc/home-ops/health.env" in unit
    assert "__INSTALL_DIR__/health/check_health.py" in unit
    assert "Type=oneshot" in unit


def test_timer_runs_every_fifteen_minutes_and_after_boot():
    timer = (DEPLOY / "vm" / "systemd" / "home-ops-health.timer").read_text()
    assert "OnUnitActiveSec=15min" in timer and "OnBootSec=" in timer and "Persistent=true" in timer


def test_provision_script_fails_fast_and_has_all_steps():
    script = DEPLOY / "vm" / "provision.sh"
    text = script.read_text()
    assert "set -euo pipefail" in text
    result = subprocess.run(["bash", str(script), "--dry-run"], capture_output=True, text=True, check=True)
    for step in ("ufw allow 443/tcp", "docker-compose-v2", "systemctl enable --now home-ops-health.timer",
                 "docker compose --project-directory", "--wait"):
        assert step in result.stdout, step


def test_skip_system_dry_run_needs_no_root():
    result = subprocess.run(["bash", str(DEPLOY / "vm" / "provision.sh"), "--skip-system", "--install-dir",
                             "/nonexistent-test-dir", "--dry-run"], capture_output=True, text=True)
    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_provision_script_passes_shellcheck():
    subprocess.run(["shellcheck", str(DEPLOY / "vm" / "provision.sh")], check=True)
