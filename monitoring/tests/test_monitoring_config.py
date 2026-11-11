"""Static checks for the monitoring stack. promtool checks the rule logic (see CI);
these tests check that the files agree with each other."""

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

MON = Path(__file__).resolve().parents[1]
RULES = MON / "prometheus" / "rules" / "home-server.yml"
PROM = MON / "prometheus" / "prometheus.yml"
AM = MON / "alertmanager" / "alertmanager.yml"
COMPOSE = MON / "docker-compose.yml"
DASH = MON / "grafana" / "dashboards" / "home-server.json"
DATASOURCE = MON / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
RUNBOOKS = MON / "runbooks"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def alerts():
    out = []
    for group in load(RULES)["groups"]:
        out.extend(group["rules"])
    return out


def test_every_alert_has_a_runbook_and_a_matching_link():
    rules = alerts()
    assert rules, "no alerts found"
    for rule in rules:
        name = rule["alert"]
        assert (RUNBOOKS / f"{name}.md").is_file(), f"missing runbook for {name}"
        assert rule["annotations"]["runbook_url"].endswith(f"/monitoring/runbooks/{name}.md")


def test_every_alert_has_a_severity_and_a_for_duration():
    for rule in alerts():
        assert rule["labels"]["severity"] in {"warning", "critical"}, rule["alert"]
        assert rule.get("for"), f"{rule['alert']} has no for: duration, so it would flap"


def test_every_alert_has_a_promtool_test():
    tests = (MON / "prometheus" / "tests" / "alerts_test.yml").read_text(encoding="utf-8")
    for rule in alerts():
        assert f"alertname: {rule['alert']}" in tests, f"no promtool case for {rule['alert']}"


def test_every_runbook_belongs_to_an_alert():
    names = {rule["alert"] for rule in alerts()}
    for path in RUNBOOKS.glob("*.md"):
        assert path.stem in names, f"{path.name} does not match any alert"


def test_alert_rules_only_use_scrape_jobs_that_exist():
    jobs = [job["job_name"] for job in load(PROM)["scrape_configs"]]
    for rule in alerts():
        for match in re.findall(r'job=~?"([^"]+)"', rule["expr"]):
            for name in match.split("|"):
                if name.endswith(".*"):  # regex prefix, e.g. lifeos.*
                    found = any(j.startswith(name[:-2]) for j in jobs)
                else:
                    found = name in jobs
                assert found, f"{rule['alert']} uses unknown job {name}"


def test_alertmanager_routes_point_at_defined_receivers():
    config = load(AM)
    receivers = {r["name"] for r in config["receivers"]}
    assert config["route"]["receiver"] in receivers
    for route in config["route"].get("routes", []):
        assert route["receiver"] in receivers


def test_compose_images_are_pinned():
    services = load(COMPOSE)["services"]
    for name, service in services.items():
        image = service.get("image", "")
        if image:
            assert ":" in image and not image.endswith(":latest"), f"{name} image is not pinned"


def test_compose_publishes_ports_only_on_localhost():
    for name, service in load(COMPOSE)["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_grafana_password_is_not_in_git():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?" in text
    assert "GF_SECURITY_ADMIN_PASSWORD: admin" not in text


def test_dashboard_is_current_and_uses_the_provisioned_datasource():
    datasource = load(DATASOURCE)["datasources"][0]["uid"]
    sys.path.insert(0, str(MON / "grafana" / "dashboards"))
    try:
        from make_dashboard import build
    finally:
        sys.path.pop(0)
    committed = json.loads(DASH.read_text(encoding="utf-8"))
    assert committed == build(), "run python monitoring/grafana/dashboards/make_dashboard.py"
    titles = {p["title"] for p in committed["panels"] if p["type"] != "row"}
    for area in ("Availability", "Performance", "Disk capacity and backups"):
        assert any(p["title"] == area for p in committed["panels"] if p["type"] == "row")
    assert any("disk" in t.lower() for t in titles)
    for panel in committed["panels"]:
        if panel["type"] == "row":
            continue
        assert panel["datasource"]["uid"] == datasource
        assert all(t["expr"] for t in panel["targets"])


def test_check_targets_script_is_executable_shell():
    script = MON / "scripts" / "check_targets.sh"
    assert script.is_file()
    assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
