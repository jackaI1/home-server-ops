import json
import time
import urllib.error
import urllib.request

import pytest
from conftest import request


def url(platform, role, path):
    return f"http://127.0.0.1:{platform['ports'][role]}{path}"


@pytest.mark.parametrize(
    ("device", "task", "status"),
    [
        ("lab-switch", "inventory", "succeeded"),
        ("lab-switch", "link-check", "succeeded"),
        ("lab-switch-faulty", "link-check", "failed"),
    ],
)
def test_real_services_execute_and_persist_audit(platform, device, task, status):
    token = platform["tokens"]["CLIENT_TOKEN"]
    code, job = request(
        url(platform, "intake", "/jobs"), token, {"device": device, "task": task}, "integration-1"
    )
    assert code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        code, result = request(url(platform, "intake", f"/jobs/{job['id']}"), token)
        if result["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert result["status"] == status
    assert result["result"]["hostname"] == device
    assert [event["event"] for event in result["events"]] == ["queued", "claimed", status]
    platform["children"][0].terminate()
    platform["children"][0].wait(timeout=5)
    platform["start"]("audit")
    assert request(url(platform, "intake", f"/jobs/{job['id']}"), token)[1] == result
    assert "lease" not in json.dumps(result)


def test_service_permissions_are_separate(platform):
    tokens = platform["tokens"]
    assert request(url(platform, "intake", "/jobs"), None, {}, "key")[0] == 401
    assert request(url(platform, "audit", "/internal/claim"), tokens["INTAKE_TOKEN"], {})[0] == 403
    assert (
        request(
            url(platform, "audit", "/jobs"),
            tokens["WORKER_TOKEN"],
            {"device": "lab-switch", "task": "inventory"},
            "key",
        )[0]
        == 403
    )
    assert (
        request(url(platform, "device", "/devices/lab-switch/version"), tokens["CLIENT_TOKEN"])[0]
        == 403
    )
    assert request(url(platform, "intake", "/internal/claim"), tokens["CLIENT_TOKEN"], {})[0] == 404


def test_validation_and_dependency_failure(platform):
    token = platform["tokens"]["CLIENT_TOKEN"]
    endpoint = url(platform, "intake", "/jobs")
    assert request(endpoint, token, {"device": "localhost", "task": "inventory"}, "key")[0] == 422
    assert request(endpoint, token, {"device": "lab-switch", "task": "inventory"})[0] == 422
    req = urllib.request.Request(
        endpoint,
        data=b"{invalid",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(req, timeout=3)
    assert error.value.code == 400
    req = urllib.request.Request(
        endpoint,
        data=b"x" * 17000,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(req, timeout=3)
    assert error.value.code == 413
    platform["children"][0].terminate()
    platform["children"][0].wait(timeout=5)
    assert request(endpoint, token, {"device": "lab-switch", "task": "inventory"}, "key")[0] == 503
    assert request(url(platform, "intake", "/readyz"))[0] == 503


def test_non_ascii_authorization_is_rejected_without_server_error(platform):
    assert request(url(platform, "intake", "/jobs"), "\xff", {}, "key")[0] == 403
