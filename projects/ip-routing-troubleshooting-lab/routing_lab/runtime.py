"""Bounded subprocess calls and evidence collection for this Compose project only."""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .cases import fault_commands
from .diagnosis import ROUTERS, diagnose, markdown_report, ospf_states, bgp_peers
from .topology import ROOT, generate, OSPF_PROBES

PROJECT = os.environ.get("ROUTING_LAB_PROJECT", "iproute-lab")


def run(args, timeout=30, check=True):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(args)}\n{p.stdout[-4000:]}")
    return p.stdout


def compose(*args, timeout=60):
    return run(["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "lab/compose.json"), *args], timeout)


def exec_router(name, *args):
    if name not in ROUTERS:
        raise ValueError(f"Unknown router {name}")
    return compose("exec", "-T", name, *args, timeout=20)


def vty(name, *commands):
    args = ["vtysh"]
    for command in commands:
        args += ["-c", command]
    output = exec_router(name, *args)
    if any(token in output for token in ("% Unknown", "% Ambiguous", "% Can't", "% Configuration failed",
                                          "Must remove previous area")):
        raise RuntimeError(output)
    return output


def ensure_stopped():
    # Docker labels work even when this checkout has no generated Compose file.
    existing = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"]).strip()
    if existing:
        raise RuntimeError("This lab project is already running. Use down before up.")


def up():
    # Never overwrite mounted config of an already running lab.
    ensure_stopped()
    version = run(["docker", "version", "--format", "{{.Server.Version}}"]).strip()
    numbers = tuple(int(n) for n in version.split(".")[:2])
    if numbers < (28, 1):
        raise RuntimeError(f"Docker Engine 28.1+ is required for fixed interface names; found {version}")
    generate()
    compose("up", "-d", "--remove-orphans", timeout=240)


def down():
    if (ROOT / "lab/compose.json").exists():
        compose("down", "--volumes", "--remove-orphans")
    remaining = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"]).strip()
    networks = run(["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"]).strip()
    if remaining or networks:
        raise RuntimeError("Cleanup incomplete: owned containers or networks remain")


def collect():
    snapshot = {"captured_at": datetime.now(timezone.utc).isoformat(), "routers": {}}
    commands = {"ospf": "show ip ospf neighbor json", "bgp": "show bgp ipv4 unicast summary json",
                "routes": "show ip route json", "isis": "show isis neighbor", "config": "show running-config",
                "ldp": "show mpls ldp neighbor", "labels": "show mpls table"}
    for name in ROUTERS:
        r = {"errors": []}
        for key, command in commands.items():
            try:
                r[key] = vty(name, command)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                r[key] = ""
                # LDP is optional; all other evidence must be available.
                if key not in ("ldp", "labels"):
                    r["errors"].append(f"{key}: {str(exc)[-500:]}")
        for key, args in {"links": ("ip", "-j", "link"), "mpls": ("cat", "/etc/frr/mpls-status")}.items():
            try:
                r[key] = exec_router(name, *args)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                r[key] = ""
                r["errors"].append(f"{key}: {str(exc)[-500:]}")
        r["logs"] = compose("logs", "--no-color", "--tail", "100", name)[-20000:]
        snapshot["routers"][name] = r
    return snapshot


def save(snapshot, directory):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    (target / "report.md").write_text(markdown_report(snapshot))


def apply_fault(name, repair=False):
    for router, kind, args in fault_commands(name, repair):
        if kind == "vtysh":
            vty(router, *args)
        else:
            exec_router(router, "ip", *args)


def fault_observed(cause, snapshot):
    west = [snapshot["routers"][name] for name in ("ce1", "pe1")]
    if cause in ("mtu-mismatch", "wrong-ospf-area"):
        return all(not any(s.startswith("Full") for s in ospf_states(r["ospf"])) for r in west)
    if cause == "bgp-prefix-filter":
        return bgp_peers(west[1]["bgp"]).get("10.10.1.2", {}).get("state") == "Established"
    if cause in ("link-down", "session-flap"):
        return bgp_peers(west[1]["bgp"]).get("10.10.1.2", {}).get("state") != "Established"
    return True


def wait_for(cause="healthy", timeout=90):
    deadline = time.monotonic() + timeout
    while True:
        snapshot = collect()
        result = diagnose(snapshot)
        if result["cause"] == cause and fault_observed(cause, snapshot):
            return snapshot
        if time.monotonic() >= deadline:
            save(snapshot, ROOT / "artifacts/last-failure")
            raise RuntimeError(f"Expected {cause}; got {result}. See artifacts/last-failure")
        time.sleep(2)


def ping_customers():
    # Service addresses force both the forward and return BGP paths to work.
    for source, destination in (("ce1", "198.18.2.1"), ("ce2", "198.18.1.1")):
        origin = "198.18.1.1" if source == "ce1" else "198.18.2.1"
        exec_router(source, "ping", "-I", origin, "-c", "2", "-W", "2", destination)


def customer_traffic_fails():
    try:
        ping_customers()
    except RuntimeError:
        return True
    return False


def ping():
    ping_customers()
    # These destinations have no BGP or static alternative: OSPF must forward them.
    for left, right in (("ce1", "pe1"), ("pe1", "ce1"), ("pe2", "ce2"), ("ce2", "pe2")):
        exec_router(left, "ping", "-I", OSPF_PROBES[left], "-c", "1", "-W", "2", OSPF_PROBES[right])


def ldp_ready(neighbors, labels, expected):
    return (len(re.findall(r"\bOPERATIONAL\b", neighbors.upper())) == expected
            and re.search(r"(?m)^\s*\d+\s+", labels) is not None)


def ownership():
    """No host ports are published; Docker owns process termination."""
    ids = compose("ps", "-aq").split()
    if not ids:
        return []
    records = json.loads(run(["docker", "inspect", *ids]))
    return [{"id": r["Id"], "pid_in_docker_host": r["State"]["Pid"], "started": r["State"]["StartedAt"],
             "ports": r["NetworkSettings"]["Ports"], "cleanup": f"ROUTING_LAB_PROJECT={PROJECT} ./scripts/lab.sh down"}
            for r in records]
