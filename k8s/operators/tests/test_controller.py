"""The controller command line: one pass with --once against the fake cluster, and bad input is refused."""

import pytest

from homeops_ops import controller
from homeops_ops.gpuqueue import API, FINALIZER, KIND
from tests.fake_kube import FakeKube
from tests.test_gpuqueue import gpujob


def test_selfheal_once_creates_the_declared_objects(tmp_path):
    manifest = tmp_path / "services.yaml"
    manifest.write_text("namespace: home-apps\nservices:\n  - name: notes\n    image: nginx:1.27-alpine\n")
    kube = FakeKube()
    assert controller.main(["selfheal", "--manifest", str(manifest), "--once"], kube=kube) == 0
    assert kube.get("apps/v1", "Deployment", "home-apps", "notes") is not None


def test_gpuqueue_once_admits_a_job(tmp_path):
    quota = tmp_path / "quota.yaml"
    quota.write_text("clusterGPUs: 2\nteams:\n  vision: 1\n")
    kube = FakeKube()
    kube.create(gpujob("a", "vision", finalizers=False))
    assert controller.main(["gpuqueue", "--quota", str(quota), "--namespace", "gpu-jobs", "--once"],
                           kube=kube) == 0
    job = kube.get(API, KIND, "gpu-jobs", "a")
    assert job["status"]["phase"] == "Admitted"
    assert FINALIZER in job["metadata"]["finalizers"]


def test_bad_manifest_is_refused_before_touching_the_cluster(tmp_path):
    manifest = tmp_path / "bad.yaml"
    manifest.write_text("services: [{name: NOPE, image: x}]\n")
    kube = FakeKube()
    with pytest.raises(ValueError):
        controller.main(["selfheal", "--manifest", str(manifest), "--once"], kube=kube)
    assert kube.calls == []


def test_loop_keeps_going_after_a_failed_pass():
    calls = []

    def step():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("API server blip")
        if len(calls) == 3:
            raise KeyboardInterrupt  # stop the loop after three passes

    controller.loop(step, 0.5, once=False, sleep=lambda _: None)
    assert len(calls) == 3
