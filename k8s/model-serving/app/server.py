"""Model serving stand-in for the home server's local model service.

It has the same shape a real model server needs for Kubernetes:
  GET  /health        liveness: the process is alive (never waits on the model)
  GET  /ready         readiness: 200 only after the model has "loaded"
  POST /v1/generate   JSON {"prompt": "..."} -> JSON reply, 503 until ready

The "model" here is a stub that echoes a short reply. It exists so the deployment,
probes, autoscaling and rollout checks can be tested without downloading model weights.
Replace the image with a real model server and keep the endpoints the same.
"""

import json
import os
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_NAME = os.environ.get("MODEL_NAME", "stub-model")
VERSION = os.environ.get("VERSION", "dev")
LOAD_SECONDS = float(os.environ.get("MODEL_LOAD_SECONDS", "2"))
STARTED = time.monotonic()
MAX_PROMPT_CHARS = 4000


def is_ready(now=None):
    now = time.monotonic() if now is None else now
    return (now - STARTED) >= LOAD_SECONDS


def generate(prompt):
    reply = f"stub reply to: {prompt[:200]}"
    return {"model": MODEL_NAME, "version": VERSION, "output": reply}


class Handler(BaseHTTPRequestHandler):
    server_version = "model-server/" + VERSION

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
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
