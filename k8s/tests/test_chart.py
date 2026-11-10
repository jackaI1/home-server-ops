import json
import subprocess
import shutil

import pytest

from conftest import CHART, find


def pod_specs(docs):
    for doc in docs:
        if doc["kind"] in ("Deployment", "StatefulSet"):
            yield doc["kind"], doc["metadata"]["name"], doc["spec"]["template"]["spec"]
        if doc["kind"] == "CronJob":
            yield "CronJob", doc["metadata"]["name"], doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def all_containers(spec):
    return list(spec.get("initContainers", [])) + list(spec["containers"])


def test_lint_passes():
    if shutil.which("helm") is None:
        pytest.fail("helm is required")
    result = subprocess.run(["helm", "lint", str(CHART), "--set", "postgres.existingSecret=postgres-credentials"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_rendered_manifests_have_the_expected_objects(render):
    docs = render()
    kinds = sorted((d["kind"], d["metadata"]["name"]) for d in docs)
    assert kinds == [
        ("CronJob", "backup"),
        ("Deployment", "telemetry"),
        ("NetworkPolicy", "allow-dns"),
        ("NetworkPolicy", "backup-egress"),
        ("NetworkPolicy", "default-deny"),
        ("NetworkPolicy", "postgres-ingress"),
        ("NetworkPolicy", "telemetry-egress"),
        ("NetworkPolicy", "telemetry-ingress"),
        ("PersistentVolumeClaim", "backups"),
        ("Service", "postgres"),
        ("Service", "telemetry"),
        ("StatefulSet", "postgres"),
    ]


def test_every_container_has_requests_and_limits(render):
    for kind, name, spec in pod_specs(render()):
        for container in all_containers(spec):
            resources = container["resources"]
            assert resources["requests"]["cpu"] and resources["requests"]["memory"], f"{kind}/{name}"
            assert resources["limits"]["cpu"] and resources["limits"]["memory"], f"{kind}/{name}"


def test_api_waits_for_the_database(render):
    spec = find(render(), "Deployment", "telemetry")["spec"]["template"]["spec"]
    init = spec["initContainers"][0]
    assert init["name"] == "wait-for-postgres"
    assert "pg_isready" in init["args"][0]


def test_long_running_pods_have_health_probes(render):
    docs = render()
    telemetry = find(docs, "Deployment", "telemetry")["spec"]["template"]["spec"]["containers"][0]
    assert telemetry["readinessProbe"]["httpGet"]["path"] == "/health"
    assert telemetry["livenessProbe"]["httpGet"]["path"] == "/health"
    postgres = find(docs, "StatefulSet", "postgres")["spec"]["template"]["spec"]["containers"][0]
    assert postgres["readinessProbe"]["exec"]["command"][0] == "pg_isready"
    assert postgres["livenessProbe"]["exec"]["command"][0] == "pg_isready"


def test_every_container_meets_restricted_pod_security(render):
    for kind, name, spec in pod_specs(render()):
        pod_context = spec.get("securityContext", {})
        assert pod_context.get("runAsNonRoot") is True, f"{kind}/{name} must run as non-root"
        assert pod_context.get("seccompProfile", {}).get("type") == "RuntimeDefault"
        for container in all_containers(spec):
            ctx = container["securityContext"]
            assert ctx["allowPrivilegeEscalation"] is False, f"{kind}/{name}"
            assert ctx["capabilities"]["drop"] == ["ALL"], f"{kind}/{name}"


def test_api_root_filesystem_is_read_only(render):
    telemetry = find(render(), "Deployment", "telemetry")["spec"]["template"]["spec"]["containers"][0]
    assert telemetry["securityContext"]["readOnlyRootFilesystem"] is True


def test_database_gets_its_password_from_a_secret_only(render):
    docs = render()
    rendered = json.dumps(docs)
    assert "local-only" not in rendered
    for kind, name in (("StatefulSet", "postgres"), ("Deployment", "telemetry")):
        spec = find(docs, kind, name)["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e for e in spec["env"]}
        assert env["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {"name": "postgres-credentials", "key": "POSTGRES_PASSWORD"}
    url = {e["name"]: e for e in find(docs, "Deployment", "telemetry")["spec"]["template"]["spec"]["containers"][0]["env"]}["DATABASE_URL"]["value"]
    assert url.endswith("@postgres:5432/telemetry")


def test_chart_refuses_to_render_without_a_secret(tmp_path):
    from conftest import helm_template
    with pytest.raises(RuntimeError, match="existingSecret must name a Secret"):
        helm_template(tmp_path, {"postgres": {"existingSecret": ""}})


def test_postgres_has_persistent_storage_and_a_subdirectory(render):
    docs = render()
    sts = find(docs, "StatefulSet", "postgres")
    claim = sts["spec"]["volumeClaimTemplates"][0]
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "5Gi"
    env = {e["name"]: e.get("value") for e in sts["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["PGDATA"] == "/var/lib/postgresql/data/pgdata"


def test_backup_cronjob_writes_to_the_backup_volume(render):
    docs = render()
    cron = find(docs, "CronJob", "backup")
    assert cron["spec"]["schedule"] == "17 2 * * *"
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"
    spec = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert spec["volumes"][0]["persistentVolumeClaim"]["claimName"] == "backups"
    script = spec["containers"][0]["args"][0]
    assert "gzip -t" in script and "mv " in script and "-mtime" in script


def test_backups_can_be_turned_off(render):
    kinds = {d["kind"] for d in render({"backup": {"enabled": False}})}
    assert "CronJob" not in kinds and "PersistentVolumeClaim" not in kinds


def test_values_flow_through_to_the_manifests(render):
    docs = render({"telemetry": {"image": {"repository": "ghcr.example/telemetry", "tag": "1.2.3"}},
                   "postgres": {"storage": {"size": "20Gi"}}})
    image = find(docs, "Deployment", "telemetry")["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == "ghcr.example/telemetry:1.2.3"
    assert find(docs, "StatefulSet", "postgres")["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"] == "20Gi"


def test_labelled_clients_get_their_own_egress_rule(render):
    docs = render({"telemetry": {"ingress": {"fromPodLabels": {"access": "telemetry-client"}}}})
    policy = find(docs, "NetworkPolicy", "telemetry-clients-egress")
    assert policy["spec"]["podSelector"] == {"matchLabels": {"access": "telemetry-client"}}
    assert policy["spec"]["egress"][0]["ports"] == [{"protocol": "TCP", "port": 8000}]
    assert "telemetry-clients-egress" not in {d["metadata"]["name"] for d in render()}
