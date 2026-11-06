"""Real kind checks, using only owned pods and no host port-forward processes."""

import json
import os
import subprocess
import time
from pathlib import Path

NS = "device-automation"


def kubectl(*args, input=None):
    return subprocess.check_output(["kubectl", "-n", NS, *args], input=input, text=True)


def pod(name, label):
    spec = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": NS, "labels": {"app": label}},
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "client",
                    "image": "device-automation:local",
                    "imagePullPolicy": "Never",
                    "command": ["python", "-c", "import time; time.sleep(3600)"],
                    "env": [
                        {
                            "name": "CLIENT_TOKEN",
                            "valueFrom": {"secretKeyRef": {"name": "client-auth", "key": "token"}},
                        }
                    ],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "16Mi"},
                        "limits": {"cpu": "100m", "memory": "64Mi"},
                    },
                }
            ],
        },
    }
    kubectl("apply", "-f", "-", input=json.dumps(spec))
    kubectl("wait", "--for=condition=Ready", f"pod/{name}", "--timeout=90s")


def execute(target, code):
    return kubectl("exec", "-i", target, "--", "python", "-", input=code).strip()


def api(path, payload=None, key=None, authenticated=True):
    return json.loads(
        execute(
            "smoke-client",
            f"""
import json, os, urllib.request, urllib.error
headers = {{'Content-Type': 'application/json'}}
if {authenticated!r}:
    headers['Authorization'] = 'Bearer ' + os.environ['CLIENT_TOKEN']
if {key!r}:
    headers['Idempotency-Key'] = {key!r}
data = None if {payload!r} is None else json.dumps({payload!r}).encode()
req = urllib.request.Request('http://intake:8080{path}', data=data, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=5) as response:
        print(json.dumps([response.status, json.load(response)]))
except urllib.error.HTTPError as error:
    print(json.dumps([error.code, json.load(error)]))
""",
        )
    )


def blocked(source, host):
    # Resolve first: DNS failure cannot masquerade as a successful isolation test.
    result = execute(
        source,
        f"""
import socket
ip = socket.gethostbyname({host!r})
try:
    with socket.create_connection((ip, 8080), timeout=3):
        raise SystemExit('FORBIDDEN CONNECTION SUCCEEDED')
except (TimeoutError, ConnectionRefusedError):
    print('blocked')
""",
    )
    assert result == "blocked", result


def main():
    owned = ["smoke-client", "smoke-untrusted"]
    summary = {
        "terminal_jobs": 0,
        "blocked_paths": 0,
        "durability": False,
        "restricted_containers": 0,
        "auth_validation_checks": 0,
    }
    try:
        pod("smoke-client", "client")
        pod("smoke-untrusted", "untrusted")
        assert api("/jobs", {}, "bad", authenticated=False)[0] == 401
        assert api("/jobs", {"device": "external-host", "task": "inventory"}, "bad")[0] == 422
        summary["auth_validation_checks"] = 2
        saved = None
        for index, (device, task, expected) in enumerate(
            [
                ("lab-switch", "inventory", "succeeded"),
                ("lab-switch", "link-check", "succeeded"),
                ("lab-switch-faulty", "link-check", "failed"),
            ]
        ):
            payload = {"device": device, "task": task}
            code, job = api("/jobs", payload, f"smoke-{index}")
            assert code == 202
            assert api("/jobs", payload, f"smoke-{index}")[1]["id"] == job["id"]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                code, result = api(f"/jobs/{job['id']}")
                if result["status"] in ("succeeded", "failed"):
                    break
                time.sleep(0.5)
            assert code == 200 and result["status"] == expected, result
            assert result["result"]["hostname"] == device
            assert [event["event"] for event in result["events"]] == ["queued", "claimed", expected]
            saved = result
            summary["terminal_jobs"] += 1
        kubectl("delete", "pod", "-l", "app=audit", "--wait=true")
        kubectl("rollout", "status", "deployment/audit", "--timeout=120s")
        assert api(f"/jobs/{saved['id']}")[1] == saved
        summary["durability"] = True
        # Healthy readiness from the host proves these targets are listening first.
        for source, host in [
            ("smoke-untrusted", "intake"),
            ("smoke-untrusted", "audit"),
            ("smoke-client", "audit"),
            ("deployment/intake", "device"),
        ]:
            blocked(source, host)
            summary["blocked_paths"] += 1
        for role in ("intake", "audit", "worker", "device"):
            result = execute(
                f"deployment/{role}",
                """
import importlib.util, os
from pathlib import Path
assert os.getuid() == 10001
assert importlib.util.find_spec('pip') is None
assert importlib.util.find_spec('ensurepip') is None
assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
try:
    Path('/app/forbidden-write').write_text('bad')
except OSError as error:
    assert error.errno == 30, error  # EROFS, not merely a file permission denial
else:
    raise SystemExit('Root filesystem was writable')
print('restricted')
""",
            )
            assert result == "restricted"
            summary["restricted_containers"] += 1
        # Authentication still rejects a wrong role on an otherwise permitted network path.
        assert (
            execute(
                "deployment/worker",
                """
import json, os, urllib.request, urllib.error
req = urllib.request.Request('http://audit:8080/jobs',
    data=json.dumps({'device': 'lab-switch', 'task': 'inventory'}).encode(),
    headers={'Authorization': 'Bearer ' + os.environ['WORKER_TOKEN'],
             'Content-Type': 'application/json', 'Idempotency-Key': 'forbidden'})
try:
    urllib.request.urlopen(req, timeout=3)
except urllib.error.HTTPError as error:
    assert error.code == 403
    print('rejected')
else:
    raise SystemExit('Worker created a job')
""",
            )
            == "rejected"
        )
        summary["auth_validation_checks"] += 1
        output = Path(os.environ.get("ARTIFACT_DIR", "/tmp/device-automation-evidence"))
        output.mkdir(parents=True, exist_ok=True)
        (output / "smoke.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    finally:
        for name in owned:
            subprocess.run(
                [
                    "kubectl",
                    "-n",
                    NS,
                    "delete",
                    "pod",
                    name,
                    "--ignore-not-found=true",
                    "--wait=true",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
