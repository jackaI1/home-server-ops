"""A tiny TCP stub used by the netns test.

    sensor_stub.py serve --bind 192.168.50.10 --port 8080    answer 'ok' to every connection
    sensor_stub.py probe 192.168.50.10 8080 --timeout 3      print ok, refused or timeout

A dropped packet shows up as 'timeout' (no answer at all), which is how the firewall tests tell a
silent drop from a refused connection.
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import sys


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            self.request.recv(64)
            self.request.sendall(b"ok\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(bind: str, port: int) -> None:
    with _Server((bind, port), _Handler) as server:
        server.serve_forever()


def probe(host: str, port: int, timeout: float) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"ping\n")
            reply = sock.recv(16)
            return "ok" if reply.startswith(b"ok") else "bad-reply"
    except ConnectionRefusedError:
        return "refused"
    except (TimeoutError, socket.timeout):
        return "timeout"
    except OSError as exc:
        return f"error:{exc.__class__.__name__}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--bind", required=True)
    s.add_argument("--port", type=int, required=True)
    p = sub.add_parser("probe")
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        serve(args.bind, args.port)
        return 0
    outcome = probe(args.host, args.port, args.timeout)
    print(outcome)
    return 0 if outcome == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
