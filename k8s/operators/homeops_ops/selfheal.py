"""Keeps the services in a manifest running as declared.

For each service it wants four objects: a Deployment, a Service, a cert-manager Issuer that signs
with its own key (self-signed), and a Certificate that cert-manager turns into a TLS Secret.
Each pass creates anything missing (a deleted object comes back), and patches anything that differs
from the manifest (a drifted replica count or image is put back). Fields that Kubernetes fills in
by itself, such as status, are ignored, so a healthy object is left alone."""

import re

import yaml

CERT_API = "cert-manager.io/v1"
DNS_LABEL = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")


def load_manifest(source):
    """Read a manifest from a file path or a dict, and check it. Returns the checked dict."""
    if isinstance(source, dict):
        data = source
    else:
        with open(source, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    return validate(data)


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        raise ValueError("manifest needs a 'services' list")
    namespace = data.get("namespace", "home-apps")
    if not DNS_LABEL.match(namespace):
        raise ValueError(f"bad namespace {namespace!r}")
    seen = set()
    services = []
    for raw in data["services"]:
        name = raw.get("name", "")
        if not DNS_LABEL.match(name):
            raise ValueError(f"bad service name {name!r}")
        if name in seen:
            raise ValueError(f"duplicate service {name!r}")
        seen.add(name)
        if not raw.get("image"):
            raise ValueError(f"{name}: image is required")
        port = raw.get("port", 80)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"{name}: port must be 1-65535")
        replicas = raw.get("replicas", 1)
        if not isinstance(replicas, int) or replicas < 0:
            raise ValueError(f"{name}: replicas must be 0 or more")
        host = raw.get("host", f"{name}.home.test")
        services.append({"name": name, "image": raw["image"], "port": port, "replicas": replicas, "host": host})
    return {"namespace": namespace, "services": services}


def desired_objects(svc, namespace):
    name = svc["name"]
    labels = {"app.kubernetes.io/name": name, "homeops.local/managed-by": "selfheal"}
    selector = {"app.kubernetes.io/name": name}
    return [
        {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {
                "replicas": svc["replicas"],
                "selector": {"matchLabels": selector},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "securityContext": {"runAsNonRoot": False},
                        "containers": [{
                            "name": name,
                            "image": svc["image"],
                            "ports": [{"name": "http", "containerPort": svc["port"]}],
                            "resources": {"limits": {"cpu": "200m", "memory": "128Mi"}},
                        }],
                    },
                },
            },
        },
        {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {"selector": selector, "ports": [{"name": "http", "port": 80, "targetPort": "http"}]},
        },
        {
            "apiVersion": CERT_API, "kind": "Issuer",
            "metadata": {"name": f"{name}-selfsigned", "namespace": namespace, "labels": labels},
            "spec": {"selfSigned": {}},
        },
        {
            "apiVersion": CERT_API, "kind": "Certificate",
            "metadata": {"name": f"{name}-tls", "namespace": namespace, "labels": labels},
            "spec": {
                "secretName": f"{name}-tls",
                "dnsNames": [svc["host"]],
                "duration": "2160h",
                "renewBefore": "720h",
                "issuerRef": {"name": f"{name}-selfsigned", "kind": "Issuer"},
            },
        },
    ]


def is_subset(want, have):
    """True when every value in `want` is found in `have`. Extra fields in `have` are fine."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and is_subset(v, have[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(have, list) and len(want) == len(have) and all(
            is_subset(w, h) for w, h in zip(want, have))
    return want == have


def reconcile(kube, manifest):
    """One pass over the manifest. Returns the actions taken, as (action, kind, name) tuples."""
    actions = []
    for svc in manifest["services"]:
        for obj in desired_objects(svc, manifest["namespace"]):
            kind, name = obj["kind"], obj["metadata"]["name"]
            namespace = obj["metadata"]["namespace"]
            actual = kube.get(obj["apiVersion"], kind, namespace, name)
            if actual is None:
                kube.create(obj)
                actions.append(("create", kind, name))
            elif not is_subset(obj["spec"], actual.get("spec", {})):
                kube.patch(obj["apiVersion"], kind, namespace, name, {"spec": obj["spec"]})
                actions.append(("patch", kind, name))
    return actions
