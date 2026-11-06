#!/usr/bin/env python3
"""Run real Nmap against a synthetic loopback banner and always release the socket."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vuln_tracker.cli import data_directory
from vuln_tracker.nvd import load_snapshot
from vuln_tracker.tracker import Tracker

ROOT = Path(__file__).resolve().parents[1]


class LabHandler(BaseHTTPRequestHandler):
    patched = False

    def handle(self):
        # A TCP connect scan closes its probe without an HTTP request.
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("X-Lab-Tracker", "synthetic")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def version_string(self):
        return "Apache/2.4.62" if self.patched else "Apache/2.4.49"

    def log_message(self, *args):
        pass


def process_start(pid):
    return subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="], text=True).strip()


def run_lab(output):
    if not shutil.which("nmap"):
        raise ValueError("Install Nmap: brew install nmap, or sudo apt-get install nmap")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Choose an empty output directory to preserve earlier lab runs")
    server = ThreadingHTTPServer(("127.0.0.1", 0), LabHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="owned-lab-http")
    resources = {
        "owner": "scripts/run_lab.py",
        "pid": os.getpid(),
        "process_start": process_start(os.getpid()),
        "port": port,
        "cleanup_command": f"kill -TERM {os.getpid()}",
        "nmap_processes": [],
    }
    thread.start()
    result = {}
    try:
        data = data_directory()
        snapshot = load_snapshot(data / "nvd-snapshot.json", data / "nvd-manifest.json")
        with Tracker(output / "lab.sqlite", snapshot) as tracker:
            for phase, on in [("before", "2026-01-01"), ("after", "2026-01-02")]:
                LabHandler.patched = phase == "after"
                xml = output / f"{phase}.xml"
                args = [
                    "nmap",
                    "-n",
                    "-Pn",
                    "-sT",
                    "-p",
                    str(port),
                    "--script",
                    str(ROOT / "lab/http-lab-cve.nse"),
                    "--script-timeout",
                    "10s",
                    "--host-timeout",
                    "20s",
                    "-oX",
                    str(xml),
                    "127.0.0.1",
                ]
                with subprocess.Popen(
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
                ) as proc:
                    resources["nmap_processes"].append(
                        {
                            "pid": proc.pid,
                            "process_start": process_start(proc.pid),
                            "port": port,
                            "cleanup_command": f"kill -TERM {proc.pid}",
                        }
                    )
                    (output / "resources.json").write_text(json.dumps(resources, indent=2) + "\n")
                    try:
                        _, error = proc.communicate(timeout=35)
                    except BaseException:
                        proc.kill()
                        proc.communicate()
                        raise
                    if proc.returncode:
                        raise ValueError("Nmap failed: " + error[-2000:])
                if phase == "after":
                    tracker.update(
                        "127.0.0.1",
                        "CVE-2021-41773",
                        "pending_validation",
                        owner="Local lab",
                        note="Changed synthetic banner to patched version",
                    )
                result[phase] = tracker.ingest(
                    xml, on, "synthetic-http", ["127.0.0.1"] if phase == "after" else []
                )
            result["report"] = tracker.report("2026-01-03")
            assert result["before"]["new"] == 1 and result["after"]["fixed"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with socket.socket() as probe:
            socket_closed = probe.connect_ex(("127.0.0.1", port)) != 0
        result["cleanup"] = {
            "socket_closed": socket_closed,
            "server_thread_stopped": not thread.is_alive(),
        }
        resources["cleanup"] = result["cleanup"]
        (output / "resources.json").write_text(json.dumps(resources, indent=2) + "\n")
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if not all(result["cleanup"].values()):
        raise RuntimeError("Lab resources did not close")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".lab-output") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
    )
    args = parser.parse_args()
    result = run_lab(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "new": result["before"]["new"],
                "fixed": result["after"]["fixed"],
                "cleanup": result["cleanup"],
            }
        )
    )
