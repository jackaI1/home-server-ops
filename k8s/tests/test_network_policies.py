"""Checks what the rendered NetworkPolicies allow, using the same rules Kubernetes applies.

A flow is allowed only if some policy selects the destination pod and has a rule that
matches the source and port. A pod that no policy selects is open. Because the chart
selects every pod with default-deny, that rule governs the rest of the namespace.
The end-to-end script in k8s/scripts checks the same flows on a real cluster.
"""
import pytest

from conftest import find

NS = "home-ops"
KUBE_SYSTEM = "kube-system"
DNS = {"ns": KUBE_SYSTEM, "labels": {"k8s-app": "kube-dns"}}

TELEMETRY = {"ns": NS, "labels": {"app.kubernetes.io/name": "telemetry", "app.kubernetes.io/component": "telemetry"}}
POSTGRES = {"ns": NS, "labels": {"app.kubernetes.io/name": "postgres", "app.kubernetes.io/component": "database"}}
BACKUP = {"ns": NS, "labels": {"app.kubernetes.io/name": "backup", "app.kubernetes.io/component": "backup"}}
STRANGER = {"ns": NS, "labels": {"app": "unrelated"}}
OTHER_NS = {"ns": "default", "labels": {"app": "unrelated"}}
TRAEFIK = {"ns": KUBE_SYSTEM, "labels": {"app.kubernetes.io/name": "traefik"}}
CLIENT = {"ns": NS, "labels": {"access": "telemetry-client"}}
INTERNET = None


def selects(selector, pod, policy_ns=NS):
    """Does a podSelector/namespaceSelector pair (or a bare selector) match this pod?

    A selector with no namespaceSelector only matches pods in the policy's own namespace.
    """
    if selector is None:
        return False
    namespace = selector.get("namespaceSelector")
    if namespace is None:
        if pod["ns"] != policy_ns:
            return False
    elif pod["ns"] != namespace.get("matchLabels", {}).get("kubernetes.io/metadata.name"):
        return False
    pod_selector = selector.get("podSelector")
    if pod_selector is not None:
        labels = pod_selector.get("matchLabels", {})
        if any(pod["labels"].get(k) != v for k, v in labels.items()):
            return False
    return True


def ports_match(ports, port):
    return ports is None or any(p["port"] == port for p in ports)


def flow_allowed(policies, src, dst, port):
    """Return True if the flow src -> dst on port is allowed by the rendered policies.

    Egress is checked on the source pod and ingress on the destination pod. A pod outside
    the policy namespace is not governed by these policies, so its side is always open.
    """
    return _side_ok(policies, "Egress", owner=src, peer=dst, port=port) and \
        _side_ok(policies, "Ingress", owner=dst, peer=src, port=port)


def _side_ok(policies, direction, owner, peer, port):
    if owner is None or owner["ns"] != NS:
        return True
    selecting = [p for p in policies
                 if direction in p["spec"].get("policyTypes", [])
                 and selects({"podSelector": p["spec"]["podSelector"]}, owner)]
    if not selecting:
        return True  # no policy selects this pod for this direction, so it is open
    if peer is None:
        return False  # the peer is outside the cluster, and no rule admits it
    rules_key, peer_key = ("ingress", "from") if direction == "Ingress" else ("egress", "to")
    for policy in selecting:
        for rule in policy["spec"].get(rules_key, []):
            peers = rule.get(peer_key)
            peer_ok = peers is None or any(selects(entry, peer) for entry in peers)
            if peer_ok and ports_match(rule.get("ports"), port):
                return True
    return False


@pytest.fixture
def policies(render):
    docs = render({"telemetry": {"ingress": {"fromNamespaces": ["kube-system"], "fromPodLabels": {"access": "telemetry-client"}}}})
    return [d for d in docs if d["kind"] == "NetworkPolicy"]


def test_default_deny_selects_every_pod_in_the_namespace(render):
    policy = find(render(), "NetworkPolicy", "default-deny")
    assert policy["spec"]["podSelector"] == {}
    assert sorted(policy["spec"]["policyTypes"]) == ["Egress", "Ingress"]
    assert "ingress" not in policy["spec"] and "egress" not in policy["spec"]


@pytest.mark.parametrize("src,dst,port,expected", [
    (TELEMETRY, POSTGRES, 5432, True),
    (BACKUP, POSTGRES, 5432, True),
    (STRANGER, POSTGRES, 5432, False),
    (OTHER_NS, POSTGRES, 5432, False),
    (TRAEFIK, POSTGRES, 5432, False),
    (TELEMETRY, POSTGRES, 22, False),
    (CLIENT, POSTGRES, 5432, False),
    (TRAEFIK, TELEMETRY, 8000, True),
    (OTHER_NS, TELEMETRY, 8000, False),
    (STRANGER, TELEMETRY, 8000, False),
    (CLIENT, TELEMETRY, 8000, True),
    (TELEMETRY, INTERNET, 443, False),
    (BACKUP, INTERNET, 443, False),
    (TELEMETRY, DNS, 53, True),
    (POSTGRES, DNS, 53, True),
    (STRANGER, DNS, 53, True),
    (STRANGER, DNS, 443, False),
    (BACKUP, TELEMETRY, 8000, False),
])
def test_flows(policies, src, dst, port, expected):
    assert flow_allowed(policies, src, dst, port) is expected


def test_api_port_follows_values(render):
    docs = render({"telemetry": {"port": 9000}})
    ingress = find(docs, "NetworkPolicy", "telemetry-ingress")["spec"]["ingress"][0]
    assert ingress["ports"] == [{"protocol": "TCP", "port": 9000}]


def test_empty_ingress_lists_are_refused(tmp_path):
    from conftest import helm_template
    with pytest.raises(RuntimeError, match="would allow all traffic"):
        helm_template(tmp_path, {"telemetry": {"ingress": {"fromNamespaces": [], "fromPodLabels": {}}}})
