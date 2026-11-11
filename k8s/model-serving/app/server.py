"""Model serving stand-in for the home server's local model service.

It has the same shape a real model server needs for Kubernetes:
  GET  /health        liveness: the process is alive (never waits on the model)
  GET  /ready         readiness: 200 only after the model has "loaded"
  POST /v1/generate   JSON {"prompt": "..."} -> JSON reply, 503 until ready
  GET  /metrics       Prometheus text: request counts and latency per route and status

The "model" here is a stub that echoes a short reply. It exists so the deployment,
probes, autoscaling and rollout checks can be tested without downloading model weights.
Replace the image with a real model server and keep the endpoints the same.
"""

import json
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = os.environ.get("MODEL_NAME", "stub-model")
VERSION = os.environ.get("VERSION", "dev")
LOAD_SECONDS = float(os.environ.get("MODEL_LOAD_SECONDS", "2"))
STARTED = time.monotonic()
MAX_PROMPT_CHARS = 4000
# Upper bounds (seconds) of the latency histogram buckets. Prometheus adds the +Inf bucket itself.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class Metrics:
    """Request counts and latency histogram, rendered in the Prometheus text format."""

    def __init__(self, buckets=LATENCY_BUCKETS):
        self.buckets = buckets
        self.lock = threading.Lock()
        self.counts = {}  # (route, code) -> requests
        self.hist = {}    # route -> [bucket counts..., total, sum]

    def observe(self, route, code, seconds):
        with self.lock:
            self.counts[(route, str(code))] = self.counts.get((route, str(code)), 0) + 1
            h = self.hist.setdefault(route, [0] * len(self.buckets) + [0, 0.0])
            for i, bound in enumerate(self.buckets):
                if seconds <= bound:
                    h[i] += 1
            h[-2] += 1
            h[-1] += seconds

    def render(self):
        lines = [
            "# HELP model_requests_total Requests handled, by route and HTTP status.",
            "# TYPE model_requests_total counter",
        ]
        with self.lock:
            for (route, code), n in sorted(self.counts.items()):
                lines.append(f'model_requests_total{{route="{route}",code="{code}"}} {n}')
            lines += [
                "# HELP model_request_duration_seconds Time spent handling a request.",
                "# TYPE model_request_duration_seconds histogram",
            ]
            for route, h in sorted(self.hist.items()):
                for i, bound in enumerate(self.buckets):
                    lines.append(f'model_request_duration_seconds_bucket{{route="{route}",le="{bound}"}} {h[i]}')
                lines.append(f'model_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} {h[-2]}')
                lines.append(f'model_request_duration_seconds_sum{{route="{route}"}} {h[-1]:.6f}')
                lines.append(f'model_request_duration_seconds_count{{route="{route}"}} {h[-2]}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()


def is_ready(now=None):
    now = time.monotonic() if now is None else now
    return (now - STARTED) >= LOAD_SECONDS


def generate(prompt):
    reply = f"stub reply to: {prompt[:200]}"
    return {"model": MODEL_NAME, "version": VERSION, "output": reply}


class Handler(BaseHTTPRequestHandler):
    server_version = "model-server/" + VERSION

    _last_code = 0

    def _send(self, status, body):
        self._last_code = status
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/metrics":
            data = METRICS.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        started = time.monotonic()
        route = "probe" if self.path in ("/health", "/ready") else "other"
        self._handle_get()
        METRICS.observe(route, self._last_code, time.monotonic() - started)

    def _handle_get(self):
        if self.path == "/health":
            self._send(200, {"status": "alive"})
        elif self.path == "/ready":
            if is_ready():
                self._send(200, {"status": "ready", "version": VERSION})
            else:
                self._send(503, {"status": "loading"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        started = time.monotonic()
        self._handle_post()
        route = "generate" if self.path == "/v1/generate" else "other"
        METRICS.observe(route, self._last_code, time.monotonic() - started)

    def _handle_post(self):
        if self.path != "/v1/generate":
            self._send(404, {"error": "not found"})
            return
        if not is_ready():
            self._send(503, {"error": "model is still loading"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            prompt = body["prompt"]
            if not isinstance(prompt, str) or not prompt or len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError("prompt must be a non-empty string up to 4000 characters")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        self._send(200, generate(prompt))

    def log_message(self, fmt, *args):
        # Keep logs quiet; probes hit /health and /ready every few seconds.
        if self.path not in ("/health", "/ready"):
            super().log_message(fmt, *args)


def make_server(port=8080):
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    httpd = make_server(int(os.environ.get("PORT", "8080")))
    # Kubernetes sends SIGTERM before it stops the pod. Exit cleanly so in-flight calls finish.
    signal.signal(signal.SIGTERM, lambda *_: httpd.shutdown())
    httpd.serve_forever()
