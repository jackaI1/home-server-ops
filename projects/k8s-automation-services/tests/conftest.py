import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def request(url, token=None, payload=None, key=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


@pytest.fixture
def platform(tmp_path):
    children = []
    ports = {}
    for role in ("audit", "device", "intake", "worker"):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            ports[role] = sock.getsockname()[1]
    tokens = {
        name: secrets.token_hex(24)
        for name in ("CLIENT_TOKEN", "INTAKE_TOKEN", "WORKER_TOKEN", "DEVICE_TOKEN")
    }
    env = {
        **os.environ,
        **tokens,
        "AUDIT_DB": str(tmp_path / "audit.db"),
        "AUDIT_URL": f"http://127.0.0.1:{ports['audit']}",
        "DEVICE_URL": f"http://127.0.0.1:{ports['device']}",
        "POLL_SECONDS": "0.05",
    }
    logs = []

    def start(role):
        log = open(tmp_path / f"{role}-{len(children)}.log", "w+")
        logs.append(log)
        process = subprocess.Popen(
            [sys.executable, "-m", "automation.server"],
            env={**env, "ROLE": role, "PORT": str(ports[role])},
            stdout=log,
            stderr=log,
        )
        children.append(process)
        # Owned PIDs, port, start time and cleanup are retained only in pytest's temp dir.
        with open(tmp_path / "ownership.txt", "a") as ownership:
            ownership.write(
                f"{role} pid={process.pid} started={time.time()} "
                f"port={ports[role]} cleanup=SIGTERM then wait\n"
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log.seek(0)
                pytest.fail(log.read(3000))
            try:
                if request(f"http://127.0.0.1:{ports[role]}/readyz")[0] == 200:
                    return process
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        pytest.fail(f"{role} did not become ready")

    try:
        for role in ("audit", "device", "intake", "worker"):
            start(role)
        yield {"ports": ports, "tokens": tokens, "start": start, "children": children}
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for log in logs:
            log.close()
        # A child that is reaped cannot retain its listening socket.
        assert all(child.poll() is not None for child in children)
