"""Tests for the stub model server: the probe endpoints and the generate contract."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def server(monkeypatch):
    import importlib.util

    monkeypatch.setenv("MODEL_NAME", "stub-test")
    monkeypatch.setenv("VERSION", "9.9.9")
    spec = importlib.util.spec_from_file_location("server_under_test", APP / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LOAD_SECONDS = 0.0
    httpd = module.make_server(0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield module, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_health_and_ready_answer_once_loaded(server):
    _, base = server
    assert call(f"{base}/health")[0] == 200
    status, body = call(f"{base}/ready")
    assert status == 200 and body["version"] == "9.9.9"


def test_ready_waits_for_the_model_to_load(server, monkeypatch):
    module, base = server
    module.LOAD_SECONDS = 3600
    assert call(f"{base}/health")[0] == 200  # alive, so liveness passes while it loads
    assert call(f"{base}/ready")[0] == 503   # not ready, so no traffic reaches it yet
    status, _ = call(f"{base}/v1/generate", json.dumps({"prompt": "hi"}).encode())
    assert status == 503


def test_generate_returns_model_and_version(server):
    _, base = server
    status, body = call(f"{base}/v1/generate", json.dumps({"prompt": "hello"}).encode())
    assert status == 200
    assert body == {"model": "stub-test", "version": "9.9.9", "output": "stub reply to: hello"}


@pytest.mark.parametrize("payload", [b"not json", b'{"prompt": 3}', b'{"prompt": ""}', b"{}"])
def test_generate_rejects_bad_input(server, payload):
    _, base = server
    assert call(f"{base}/v1/generate", payload)[0] == 400


def test_unknown_paths_are_404(server):
    _, base = server
    assert call(f"{base}/nope")[0] == 404


def test_metrics_count_requests_and_latency(server):
    module, base = server
    module.METRICS = module.Metrics()  # start from zero so the counts are exact
    call(base + "/v1/generate", json.dumps({"prompt": "hi"}).encode())
    call(base + "/v1/generate", b"{}")  # 400: no prompt
    call(base + "/ready")
    text = urllib.request.urlopen(base + "/metrics", timeout=5).read().decode()
    assert 'model_requests_total{route="generate",code="200"} 1' in text
    assert 'model_requests_total{route="generate",code="400"} 1' in text
    assert 'model_requests_total{route="probe",code="200"} 1' in text
    assert 'model_request_duration_seconds_count{route="generate"} 2' in text
    assert 'model_request_duration_seconds_bucket{route="generate",le="+Inf"} 2' in text
    assert "# TYPE model_request_duration_seconds histogram" in text
