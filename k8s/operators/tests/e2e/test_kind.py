"""End-to-end tests against a real cluster (kind in CI). They run only when HOMEOPS_E2E=1,
because they need a cluster with cert-manager, the GPUJob CRD and both controllers running.
scripts/e2e-kind.sh sets all of that up."""

import os
import time

import pytest

from homeops_ops import gpuqueue
from homeops_ops.kube import Kube

pytestmark = pytest.mark.skipif(os.environ.get("HOMEOPS_E2E") != "1", reason="set HOMEOPS_E2E=1 on a kind cluster")

APPS = "home-apps"
JOBS = "gpu-jobs"


@pytest.fixture(scope="module")
def kube():
    return Kube()


def wait_for(check, timeout=120, every=2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = check()
        if last:
            return last
        time.sleep(every)
    raise AssertionError(f"timed out after {timeout}s; last value: {last!r}")


def test_selfheal_restores_a_deleted_deployment(kube):
    before = wait_for(lambda: kube.get("apps/v1", "Deployment", APPS, "notes"))
    kube.delete("apps/v1", "Deployment", APPS, "notes")
    after = wait_for(lambda: kube.get("apps/v1", "Deployment", APPS, "notes"))
    assert after["metadata"]["uid"] != before["metadata"]["uid"], "it must be a new object"
    ready = wait_for(lambda: (kube.get("apps/v1", "Deployment", APPS, "notes") or {}).get("status", {})
                     .get("readyReplicas"), timeout=180)
    assert ready == 1


def test_selfheal_reissues_a_deleted_certificate_and_cert_manager_fills_the_secret(kube):
    wait_for(lambda: kube.get("cert-manager.io/v1", "Certificate", APPS, "wiki-tls"))
    kube.delete("cert-manager.io/v1", "Certificate", APPS, "wiki-tls")
    wait_for(lambda: kube.get("cert-manager.io/v1", "Certificate", APPS, "wiki-tls"))
    secret = wait_for(lambda: kube.get("v1", "Secret", APPS, "wiki-tls"), timeout=180)
    assert secret["type"] == "kubernetes.io/tls"
    assert secret["data"]["tls.crt"]


def gpujob(name, team, command):
    return {"apiVersion": gpuqueue.API, "kind": gpuqueue.KIND,
            "metadata": {"name": name, "namespace": JOBS},
            "spec": {"team": team, "gpus": 1, "image": "busybox:1.36", "command": command}}


def phase_of(kube, name):
    obj = kube.get(gpuqueue.API, gpuqueue.KIND, JOBS, name) or {}
    return (obj.get("status") or {}).get("phase")


def test_gpu_queue_holds_jobs_until_quota_and_capacity_allow(kube):
    # Team vision may hold 1 GPU, and the cluster has 2. The second vision job must wait for the first.
    kube.create(gpujob("vision-a", "vision", ["sh", "-c", "sleep 15"]))
    kube.create(gpujob("vision-b", "vision", ["sh", "-c", "sleep 5"]))
    kube.create(gpujob("bench-a", "benchmarks", ["sh", "-c", "sleep 60"]))

    wait_for(lambda: phase_of(kube, "vision-a") == "Admitted")
    wait_for(lambda: phase_of(kube, "bench-a") == "Admitted")
    queued = wait_for(lambda: kube.get(gpuqueue.API, gpuqueue.KIND, JOBS, "vision-b")["status"]
                      if phase_of(kube, "vision-b") == "Queued" else None)
    assert queued["reason"] == "TeamQuota" and queued["position"] == 1

    # When vision-a finishes, its GPU goes to vision-b.
    wait_for(lambda: phase_of(kube, "vision-a") == "Succeeded", timeout=180)
    wait_for(lambda: phase_of(kube, "vision-b") == "Admitted", timeout=60)
    wait_for(lambda: phase_of(kube, "vision-b") == "Succeeded", timeout=180)


def test_deleting_a_running_gpujob_removes_its_batch_job(kube):
    kube.create(gpujob("cancel-me", "benchmarks", ["sh", "-c", "sleep 300"]))
    wait_for(lambda: phase_of(kube, "cancel-me") == "Admitted")
    kube.delete(gpuqueue.API, gpuqueue.KIND, JOBS, "cancel-me")
    wait_for(lambda: kube.get("batch/v1", "Job", JOBS, "cancel-me-run") is None, timeout=120)
    wait_for(lambda: kube.get(gpuqueue.API, gpuqueue.KIND, JOBS, "cancel-me") is None, timeout=120)
