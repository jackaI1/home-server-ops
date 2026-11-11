"""Stand-in alert receiver for the monitoring stack.

Alertmanager POSTs JSON to /critical or /warning. This script prints one line per alert,
so `docker compose logs alert-sink` shows what would have been sent. It is not a notifier.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            print(
                f"{self.path} {alert.get('status')} {labels.get('alertname')} "
                f"{labels.get('instance', '')}",
                flush=True,
            )
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Sink).serve_forever()
