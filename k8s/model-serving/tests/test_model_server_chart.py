"""Tests for the model-server chart. They render the chart with helm and check the manifests.
The rollout behaviour itself is checked on a real kind cluster (scripts/rollout_check.sh)."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "chart"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def render(tmp_path, values=None):
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(values or {}))
    result = subprocess.run(
        ["helm", "template", "model-server", str(CHART), "--namespace", "model-serving",
         "-f", str(values_file)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def find(docs, kind):
    matches = [d for d in docs if d["kind"] == kind]
    assert len(matches) == 1, f"expected one {kind}, found {len(matches)}"
    return matches[0]


def container(docs):
    return find(docs, "Deployment")["spec"]["template"]["spec"]["containers"][0]


def test_renders_deployment_service_and_hpa(tmp_path):
    docs = render(tmp_path)
    assert {d["kind"] for d in docs} == {"Deployment", "Service", "HorizontalPodAutoscaler"}


def test_readiness_and_liveness_probes_are_set(tmp_path):
    c = container(render(tmp_path))
    assert c["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"
    # Readiness gates traffic and liveness restarts a hung process. They must be different checks.
    assert c["readinessProbe"]["httpGet"]["path"] != c["livenessProbe"]["httpGet"]["path"]
    assert c["readinessProbe"]["failureThreshold"] >= 1
    assert c["livenessProbe"]["initialDelaySeconds"] >= c["readinessProbe"]["initialDelaySeconds"]


def test_resources_have_requests_and_limits(tmp_path):
    c = container(render(tmp_path))
    assert set(c["resources"]["limits"]) >= {"cpu", "memory"}
    assert set(c["resources"]["requests"]) >= {"cpu", "memory"}


def test_container_runs_as_non_root_with_read_only_root(tmp_path):
    docs = render(tmp_path)
    pod = find(docs, "Deployment")["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    c = pod["containers"][0]
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_rolling_update_never_drops_below_full_capacity(tmp_path):
    deploy = find(render(tmp_path), "Deployment")
    assert deploy["spec"]["strategy"]["type"] == "RollingUpdate"
    assert deploy["spec"]["strategy"]["rollingUpdate"] == {"maxSurge": 1, "maxUnavailable": 0}


def test_hpa_scales_on_cpu_between_min_and_max(tmp_path):
    hpa = find(render(tmp_path), "HorizontalPodAutoscaler")
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["spec"]["minReplicas"] == 1 and hpa["spec"]["maxReplicas"] == 3
    metric = hpa["spec"]["metrics"][0]
    assert metric["resource"]["name"] == "cpu"
    assert metric["resource"]["target"]["averageUtilization"] == 70
    assert hpa["spec"]["scaleTargetRef"]["name"] == "model-server"


def test_hpa_owns_replicas_so_the_deployment_omits_them(tmp_path):
    deploy = find(render(tmp_path), "Deployment")
    assert "replicas" not in deploy["spec"]


def test_turning_autoscaling_off_sets_a_fixed_replica_count(tmp_path):
    docs = render(tmp_path, {"autoscaling": {"enabled": False}, "replicaCount": 2})
    assert find(docs, "Deployment")["spec"]["replicas"] == 2
    assert all(d["kind"] != "HorizontalPodAutoscaler" for d in docs)


def test_service_points_at_the_container_port(tmp_path):
    svc = find(render(tmp_path), "Service")
    assert svc["spec"]["ports"][0]["port"] == 80
    assert svc["spec"]["ports"][0]["targetPort"] == "http"
    assert svc["spec"]["selector"]["app.kubernetes.io/name"] == "model-server"


def test_version_comes_from_the_image_tag(tmp_path):
    c = container(render(tmp_path, {"image": {"tag": "0.2.0"}}))
    assert c["image"] == "model-server:0.2.0"
    env = {e["name"]: e["value"] for e in c["env"]}
    assert env["VERSION"] == "0.2.0"


def test_gpu_is_off_by_default(tmp_path):
    pod = find(render(tmp_path), "Deployment")["spec"]["template"]["spec"]
    assert "nodeSelector" not in pod
    assert "nvidia.com/gpu" not in container(render(tmp_path))["resources"]["limits"]


def test_gpu_pins_pod_to_gpu_node_and_requests_one_gpu(tmp_path):
    docs = render(tmp_path, {"gpu": {"enabled": True}})
    pod = find(docs, "Deployment")["spec"]["template"]["spec"]
    assert pod["nodeSelector"] == {"nvidia.com/gpu.present": "true"}
    assert {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"} in pod["tolerations"]
    limits = pod["containers"][0]["resources"]["limits"]
    assert limits["nvidia.com/gpu"] == 1
    # The GPU request must not drop the CPU and memory limits.
    assert limits["cpu"] and limits["memory"]


def test_metrics_port_is_annotated_for_prometheus(tmp_path):
    ann = find(render(tmp_path), "Deployment")["spec"]["template"]["metadata"]["annotations"]
    assert ann == {"prometheus.io/scrape": "true", "prometheus.io/port": "8080", "prometheus.io/path": "/metrics"}
