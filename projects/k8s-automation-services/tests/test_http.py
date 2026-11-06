import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from automation.domain import Problem
from automation.http import call


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, b""),
        (409, b"[]"),
        (422, b'{"error":123}'),
        (200, b"[]"),
        (200, b"false"),
        (200, b'{"text":"' + b"x" * 65536 + b'"}'),
    ],
    ids=[
        "empty-error",
        "array-error",
        "invalid-error-field",
        "array-success",
        "boolean-success",
        "oversized-success",
    ],
)
def test_malformed_upstream_is_a_recoverable_dependency_error(status, body):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with pytest.raises(Problem) as error:
            call(f"http://127.0.0.1:{server.server_port}/")
        assert error.value.status == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_worker_keeps_polling_after_malformed_upstream_error():
    from automation.worker import run

    stop = threading.Event()
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests_seen.append(self.path)
            if len(requests_seen) == 1:
                self.send_response(429)
                body = b"upstream busy"
            else:
                self.send_response(200)
                body = b"null"
                stop.set()
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    heartbeat = [0.0]
    errors = []

    def worker():
        try:
            run(
                {
                    "AUDIT_URL": f"http://127.0.0.1:{server.server_port}",
                    "WORKER_TOKEN": "not-a-real-token-for-this-fixture",
                    "POLL_SECONDS": ".01",
                },
                stop,
                heartbeat,
            )
        except Exception as error:
            errors.append(type(error).__name__)

    worker_thread = threading.Thread(target=worker)
    worker_thread.start()
    try:
        worker_thread.join(timeout=3)
        assert not errors
        assert requests_seen == ["/internal/claim", "/internal/claim"]
        assert heartbeat[0] > 0
    finally:
        stop.set()
        worker_thread.join(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        assert not worker_thread.is_alive() and not server_thread.is_alive()
