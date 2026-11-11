"""Record the packets for one command with tcpdump.

tcpdump is the standard packet recorder on Linux and macOS. This module starts
it on one interface, runs the command you give it (a backup or a sync), stops
tcpdump, and writes three files into a folder:

* capture.pcap: every packet that matched the filter, in pcap format.
* tcpdump.log: what tcpdump printed, including any dropped-packet counts.
* capture.json: when it started and ended, the command, and its exit code.

Recording needs root (or permission to use the capture device), so when we are
not root the tcpdump call is run with `sudo -n`, which fails rather than
asking for a password.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Headers only: TCP and DNS analysis needs the IP and TCP headers, not payloads.
DEFAULT_SNAPLEN = 200
# Capturing everything would fill the disk on a busy host; this is a sensible
# default for backup and sync traffic. Override it with --filter.
DEFAULT_FILTER = "tcp or udp port 53"
READY_MARKER = "listening on"


class CaptureError(RuntimeError):
    """tcpdump is missing, did not start, or could not be stopped cleanly."""


@dataclass(frozen=True)
class CaptureSpec:
    iface: str
    out_dir: Path
    bpf: str = DEFAULT_FILTER
    snaplen: int = DEFAULT_SNAPLEN

    @property
    def pcap(self) -> Path:
        return self.out_dir / "capture.pcap"

    @property
    def log(self) -> Path:
        return self.out_dir / "tcpdump.log"

    @property
    def meta(self) -> Path:
        return self.out_dir / "capture.json"


def tcpdump_command(spec: CaptureSpec, tcpdump: str) -> list[str]:
    """Build the tcpdump command line. It writes to spec.pcap until it is stopped."""
    cmd = [tcpdump, "-i", spec.iface, "-s", str(spec.snaplen), "-n", "-U", "-w", str(spec.pcap)]
    if spec.bpf.strip():
        cmd += spec.bpf.split()
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    return cmd


def _wait_until_ready(log: Path, proc: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise CaptureError(f"tcpdump exited early: {_tail(log)}")
        if log.exists() and READY_MARKER in log.read_text(errors="replace"):
            return
        time.sleep(0.05)
    raise CaptureError(f"tcpdump did not start within {timeout:.0f}s: {_tail(log)}")


def _tail(path: Path, lines: int = 5) -> str:
    if not path.exists():
        return "no output"
    return " | ".join(path.read_text(errors="replace").splitlines()[-lines:])[-400:]


def _stop(proc: subprocess.Popen) -> None:
    """Ask tcpdump to flush and exit, then kill it if it ignores us."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_capture(
    command: list[str],
    spec: CaptureSpec,
    tcpdump: str | None = None,
    ready_timeout: float = 15.0,
) -> int:
    """Record traffic while `command` runs. Returns the command's exit code.

    tcpdump is always stopped in the `finally` block, even if the command
    raises, so no capture process is left running.
    """
    tcpdump = tcpdump or shutil.which("tcpdump")
    if tcpdump is None:
        raise CaptureError("tcpdump is not installed (apt install tcpdump)")
    if not command:
        raise CaptureError("no command given to capture")

    spec.out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    with spec.log.open("w") as log:
        proc = subprocess.Popen(tcpdump_command(spec, tcpdump), stdout=log, stderr=subprocess.STDOUT)
        try:
            _wait_until_ready(spec.log, proc, ready_timeout)
            result = subprocess.run(command, check=False)
        finally:
            _stop(proc)
    meta = {
        "iface": spec.iface,
        "filter": spec.bpf,
        "command": command,
        "started": started.isoformat(),
        "ended": datetime.now(timezone.utc).isoformat(),
        "exit_code": result.returncode,
        "tcpdump_exit": proc.returncode,
    }
    spec.meta.write_text(json.dumps(meta, indent=2) + "\n")
    for path in (spec.pcap, spec.log, spec.meta, spec.out_dir):
        _hand_back_ownership(path)
    return result.returncode


def _hand_back_ownership(path: Path) -> None:
    """Files written under sudo belong to root; give them back to the user who ran us."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if os.geteuid() == 0 and uid and gid and path.exists():
        os.chown(path, int(uid), int(gid))
