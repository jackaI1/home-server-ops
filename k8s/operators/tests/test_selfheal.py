"""Reconciliation tests for selfheal: create, self-heal after deletes, and put back drifted fields."""

import pytest

from homeops_ops import selfheal
from tests.fake_kube import FakeKube

MANIFEST = {
    "namespace": "home-apps",
    "services": [
        {"name": "notes", "image": "nginx:1.27-alpine", "port": 80, "replicas": 1, "host": "notes.home.test"},
        {"name": "wiki", "image": "wiki:2", "port": 8080, "replicas": 2},
    ],
}


def kinds(actions):
    return sorted((a, k, n) for a, k, n in actions)


def test_first_pass_creates_the_four_objects_for_each_service():
    kube = FakeKube()
    actions = selfheal.reconcile(kube, selfheal.validate(MANIFEST))
    assert len(actions) == 8
    assert {k for _, k, _ in actions} == {"Deployment", "Service", "Issuer", "Certificate"}
    assert kube.get("apps/v1", "Deployment", "home-apps", "notes") is not None
    assert kube.get("cert-manager.io/v1", "Certificate", "home-apps", "wiki-tls") is not None


def test_second_pass_changes_nothing():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    assert selfheal.reconcile(kube, manifest) == []


def test_a_deleted_deployment_comes_back():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    kube.remove("apps/v1", "Deployment", "home-apps", "notes")
    actions = selfheal.reconcile(kube, manifest)
    assert actions == [("create", "Deployment", "notes")]


def test_a_deleted_certificate_is_reissued():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    kube.remove("cert-manager.io/v1", "Certificate", "home-apps", "notes-tls")
    assert selfheal.reconcile(kube, manifest) == [("create", "Certificate", "notes-tls")]


def test_drifted_replicas_are_put_back_to_the_manifest():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    kube.store[("apps/v1", "Deployment", "home-apps", "wiki")]["spec"]["replicas"] = 7
    assert selfheal.reconcile(kube, manifest) == [("patch", "Deployment", "wiki")]
    assert kube.get("apps/v1", "Deployment", "home-apps", "wiki")["spec"]["replicas"] == 2


def test_a_changed_image_is_rolled_back_to_the_manifest():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    container = kube.store[("apps/v1", "Deployment", "home-apps", "notes")]["spec"]["template"]["spec"]["containers"][0]
    container["image"] = "nginx:latest"
    selfheal.reconcile(kube, manifest)
    fixed = kube.get("apps/v1", "Deployment", "home-apps", "notes")
    assert fixed["spec"]["template"]["spec"]["containers"][0]["image"] == "nginx:1.27-alpine"


def test_fields_added_by_kubernetes_do_not_count_as_drift():
    kube = FakeKube()
    manifest = selfheal.validate(MANIFEST)
    selfheal.reconcile(kube, manifest)
    stored = kube.store[("v1", "Service", "home-apps", "notes")]
    stored["spec"]["clusterIP"] = "10.0.0.5"
    stored["spec"]["ports"][0]["protocol"] = "TCP"
    assert selfheal.reconcile(kube, manifest) == []


def test_certificate_names_the_host_and_its_own_issuer():
    objs = {o["kind"]: o for o in selfheal.desired_objects(selfheal.validate(MANIFEST)["services"][0], "home-apps")
            if o["kind"] in ("Certificate", "Issuer")}
    cert = objs["Certificate"]["spec"]
    assert cert["dnsNames"] == ["notes.home.test"]
    assert cert["secretName"] == "notes-tls"
    assert cert["issuerRef"] == {"name": "notes-selfsigned", "kind": "Issuer"}
    assert objs["Issuer"]["spec"] == {"selfSigned": {}}


@pytest.mark.parametrize("bad, message", [
    ({"services": [{"name": "Bad_Name", "image": "x"}]}, "bad service name"),
    ({"services": [{"name": "a", "image": ""}]}, "image is required"),
    ({"services": [{"name": "a", "image": "x", "port": 0}]}, "port must be"),
    ({"services": [{"name": "a", "image": "x", "replicas": -1}]}, "replicas must be"),
    ({"services": [{"name": "a", "image": "x"}, {"name": "a", "image": "y"}]}, "duplicate service"),
    ({"namespace": "Not OK", "services": []}, "bad namespace"),
    ({"nothing": 1}, "needs a 'services' list"),
])
def test_manifest_mistakes_are_refused_before_anything_changes(bad, message):
    with pytest.raises(ValueError, match=message):
        selfheal.validate(bad)


def test_example_manifest_loads():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "examples" / "services.yaml"
    manifest = selfheal.load_manifest(path)
    assert [s["name"] for s in manifest["services"]] == ["notes", "wiki"]
