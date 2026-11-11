"""Tests for the health checker: services that answer, certificates that verify and have enough days left,
and alerts sent to a webhook when something fails. The servers used here are local and short-lived."""

import importlib.util
import io
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

import pytest

HEALTH = Path(__file__).resolve().parents[1] / "health" / "check_health.py"
spec = importlib.util.spec_from_file_location("check_health", HEALTH)
ch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch)

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")


def serve(handler_cls, server_cls=ThreadingHTTPServer):
    httpd = server_cls(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def stop(httpd):
    httpd.shutdown()
    httpd.server_close()


def responder(status):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture
def http_ok():
    httpd = serve(responder(200))
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    stop(httpd)


def test_url_that_answers_200_passes(http_ok):
    result = ch.check_url(http_ok)
    assert result.ok and result.detail == "HTTP 200"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_url_that_returns_an_error_fails(status):
    httpd = serve(responder(status))
    try:
        result = ch.check_url(f"http://127.0.0.1:{httpd.server_address[1]}/")
    finally:
        stop(httpd)
    assert not result.ok and result.detail == f"HTTP {status}"


def test_url_that_is_down_fails():
    # Port 9 (discard) is not listening on this machine, so the connection is refused.
    result = ch.check_url("http://127.0.0.1:9/", timeout=2)
    assert not result.ok and "request failed" in result.detail


@pytest.fixture
def make_cert(tmp_path):
    def make(days, name="cert"):
        key, cert = tmp_path / f"{name}.key", tmp_path / f"{name}.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
             "-days", str(days), "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
             "-addext", "basicConstraints=critical,CA:TRUE"],
            check=True, capture_output=True,
        )
        return cert, key

    return make


def tls_server(cert, key):
    class Handler(responder(200)):
        pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


@needs_openssl
def test_certificate_with_plenty_of_time_passes(make_cert):
    cert, key = make_cert(400)
    httpd = tls_server(cert, key)
    try:
        result = ch.check_cert(f"localhost:{httpd.server_address[1]}", warn_days=14, cafile=str(cert))
    finally:
        stop(httpd)
    assert result.ok, result.detail


@needs_openssl
def test_certificate_close_to_expiry_fails(make_cert):
    cert, key = make_cert(10)
    httpd = tls_server(cert, key)
    try:
        result = ch.check_cert(f"localhost:{httpd.server_address[1]}", warn_days=14, cafile=str(cert))
    finally:
        stop(httpd)
    assert not result.ok and "expires in" in result.detail


@needs_openssl
def test_certificate_that_does_not_verify_fails(make_cert):
    cert, key = make_cert(400)
    httpd = tls_server(cert, key)
    try:
        # No CA file: the self-signed certificate is not trusted, so the check must fail.
        result = ch.check_cert(f"localhost:{httpd.server_address[1]}", warn_days=14, cafile=None)
    finally:
        stop(httpd)
    assert not result.ok and "does not verify" in result.detail


def test_cert_days_left_uses_the_expiry_date(monkeypatch):
    class FakeTLS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def getpeercert(self):
            return {"notAfter": "Jan  1 00:00:00 2030 GMT"}

    class FakeCtx:
        def wrap_socket(self, sock, server_hostname):
            return FakeTLS()

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ch.ssl, "create_default_context", lambda cafile=None: FakeCtx())
    monkeypatch.setattr(ch.socket, "create_connection", lambda *a, **k: FakeSock())
    not_after = ch.ssl.cert_time_to_seconds("Jan  1 00:00:00 2030 GMT")
    assert ch.cert_days_left("example.test", 443, now=not_after - 3 * 86400) == pytest.approx(3.0)


def test_main_exits_one_when_a_check_fails(http_ok):
    out = io.StringIO()
    assert ch.main(["--url", http_ok, "--tls", "127.0.0.1:9"], env={}, out=out) == 1  # TLS port is closed
    assert "OK    " + http_ok in out.getvalue() and "FAIL  tls 127.0.0.1:9" in out.getvalue()


def test_main_reads_settings_from_the_environment(http_ok):
    out = io.StringIO()
    code = ch.main([], env={"HEALTH_URLS": http_ok}, out=out)
    assert code == 0
    assert out.getvalue().startswith("OK    ")


def test_main_needs_something_to_check():
    with pytest.raises(SystemExit) as exc:
        ch.main([], env={}, out=io.StringIO())
    assert exc.value.code == 2


def test_failure_is_posted_to_the_webhook():
    received = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    hook = serve(Hook)
    try:
        url = f"http://127.0.0.1:{hook.server_address[1]}/alert"
        out = io.StringIO()
        code = ch.main(["--url", "http://127.0.0.1:9/"], env={"ALERT_WEBHOOK": url}, out=out)
    finally:
        stop(hook)
    assert code == 1
    assert len(received) == 1
    assert "request failed" in received[0]["message"]
    assert received[0]["title"].startswith("Home server check failed")


def test_unreachable_webhook_is_reported_but_exit_code_stays_one():
    out = io.StringIO()
    code = ch.main(["--url", "http://127.0.0.1:9/"], env={"ALERT_WEBHOOK": "http://127.0.0.1:9/hook"}, out=out)
    assert code == 1
    assert "could not send the alert" in out.getvalue()
