"""Run one service per process: ROLE=intake|audit|worker|device."""

import hmac
import json
import os
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from automation.domain import DEVICES, Problem, validate_job, validate_key
from automation.http import call
from automation.store import Store
from automation.worker import run

REQUIRED = {
    "intake": ("CLIENT_TOKEN", "INTAKE_TOKEN", "AUDIT_URL"),
    "audit": ("INTAKE_TOKEN", "WORKER_TOKEN", "AUDIT_DB"),
    "worker": ("WORKER_TOKEN", "DEVICE_TOKEN", "AUDIT_URL", "DEVICE_URL"),
    "device": ("DEVICE_TOKEN",),
}


def main():
    settings = dict(os.environ)
    role = settings.get("ROLE", "intake")
    if role not in REQUIRED:
        raise SystemExit("Unknown ROLE")
    for name in REQUIRED[role]:
        if not settings.get(name) or (name.endswith("_TOKEN") and len(settings[name]) < 24):
            raise SystemExit(f"{name} must be set (tokens require at least 24 characters)")
    for name in ("AUDIT_URL", "DEVICE_URL"):
        if name in REQUIRED[role]:
            parsed = urlsplit(settings[name])
            if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.query:
                raise SystemExit(f"{name} must be a fixed internal http URL")
    store = Store(settings["AUDIT_DB"]) if role == "audit" else None
    stop = threading.Event()
    heartbeat = [0.0]

    class Handler(BaseHTTPRequestHandler):
        server_version = "DeviceChecks"

        def log_message(self, fmt, *args):
            # Request headers, tokens, bodies and device results never enter access logs.
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def auth(self, name):
            header = self.headers.get("Authorization", "")
            if not header:
                raise Problem(401, "Bearer token required")
            if not hmac.compare_digest(header.encode(), f"Bearer {settings[name]}".encode()):
                raise Problem(403, "Token does not permit this operation")

        def body(self):
            if self.headers.get("Transfer-Encoding"):
                raise Problem(400, "Transfer encoding unsupported")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise Problem(400, "Invalid content length") from None
            if length < 0 or length > 16384:
                raise Problem(413, "Body exceeds 16 KiB")
            if self.headers.get_content_type() != "application/json":
                raise Problem(415, "Use application/json")
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise Problem(400, "Invalid JSON") from None
            if not isinstance(body, dict):
                raise Problem(422, "Provide a JSON object")
            return body

        def route(self):
            path = urlsplit(self.path).path
            method = self.command
            if method == "GET" and path in ("/healthz", "/readyz"):
                if path == "/readyz":
                    if role == "audit":
                        store.ready()
                    elif role == "intake":
                        call(f"{settings['AUDIT_URL']}/readyz")
                    elif role == "worker" and time.monotonic() - heartbeat[0] > 30:
                        raise Problem(503, "Worker cannot reach audit queue")
                return 200, {"status": "ok"}
            if role == "intake" and path.startswith("/jobs"):
                self.auth("CLIENT_TOKEN")
                if method == "POST" and path == "/jobs":
                    body = validate_job(self.body())
                    key = validate_key(self.headers.get("Idempotency-Key"))
                    return 202, call(
                        f"{settings['AUDIT_URL']}/jobs", settings["INTAKE_TOKEN"], body, key
                    )
                if method == "GET" and path.startswith("/jobs/"):
                    return 200, call(f"{settings['AUDIT_URL']}{path}", settings["INTAKE_TOKEN"])
            if role == "audit":
                if path == "/jobs" and method == "POST":
                    self.auth("INTAKE_TOKEN")
                    return 202, store.submit(self.headers.get("Idempotency-Key"), self.body())
                if path.startswith("/jobs/") and method == "GET":
                    self.auth("INTAKE_TOKEN")
                    return 200, store.get(path.removeprefix("/jobs/"))
                if path == "/internal/claim" and method == "POST":
                    self.auth("WORKER_TOKEN")
                    self.body()
                    return 200, store.claim()
                if path == "/internal/finish" and method == "POST":
                    self.auth("WORKER_TOKEN")
                    body = self.body()
                    if set(body) != {"id", "lease", "status", "result"} or not all(
                        isinstance(body[k], str) for k in ("id", "lease", "status")
                    ):
                        raise Problem(422, "Invalid completion")
                    return 200, store.finish(
                        body["id"], body["lease"], body["status"], body["result"]
                    )
            if role == "device" and method == "GET":
                self.auth("DEVICE_TOKEN")
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "devices" and parts[1] in DEVICES:
                    if parts[2] == "version":
                        return 200, {
                            "hostname": parts[1],
                            "model": "simulated-switch",
                            "firmware": "1.0",
                        }
                    if parts[2] == "interfaces":
                        return 200, {
                            "interfaces": [
                                {"name": "eth0", "state": "up"},
                                {
                                    "name": "eth1",
                                    "state": "down" if parts[1].endswith("faulty") else "up",
                                },
                            ]
                        }
            raise Problem(404, "Route not found")

        def handle_request(self):
            try:
                code, value = self.route()
            except Problem as error:
                code, value = error.status, {"error": str(error)}
            except (sqlite3.Error, OSError):
                code, value = 503, {"error": "Service temporarily unavailable"}
            except Exception:
                code, value = 500, {"error": "Request failed"}
            data = json.dumps(value).encode()
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(("0.0.0.0", int(settings.get("PORT", "8080"))), Handler)
    server.daemon_threads = True
    server.timeout = 0.5
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    thread = None
    if role == "worker":
        thread = threading.Thread(target=run, args=(settings, stop, heartbeat), daemon=True)
        thread.start()
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        server.server_close()
        if thread:
            thread.join(timeout=6)


if __name__ == "__main__":
    main()
