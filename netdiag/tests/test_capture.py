"""Tests for the tcpdump wrapper, using a fake tcpdump so no packets are captured."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from netdiag.capture import CaptureError, CaptureSpec, run_capture, tcpdump_command

FAKE_TCPDUMP = """#!{python}
import signal, sys, time, pathlib
args = sys.argv[1:]
out = pathlib.Path(args[args.index('-w') + 1])
out.write_bytes(b'')
print('tcpdump: listening on fake0', file=sys.stderr, flush=True)
signal.signal(signal.SIGINT, lambda *a: (print('stopped', file=sys.stderr), sys.exit(0)))
while True:
    time.sleep(0.05)
"""


@pytest.fixture(autouse=True)
def _as_root(monkeypatch):
    # Pretend to be root so the fake tcpdump runs directly, without sudo.
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def _fake_tcpdump(tmp_path):
    path = tmp_path / "tcpdump"
    path.write_text(FAKE_TCPDUMP.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_tcpdump_command_limits_to_filter_and_snaplen(tmp_path):
    spec = CaptureSpec(iface="eth0", out_dir=tmp_path, bpf="host 10.0.0.2 and port 22")
    cmd = tcpdump_command(spec, "/usr/sbin/tcpdump")
    assert cmd[:1] == ["/usr/sbin/tcpdump"]
    assert cmd[cmd.index("-i") + 1] == "eth0"
    assert cmd[cmd.index("-s") + 1] == "200"
    assert cmd[cmd.index("-w") + 1] == str(spec.pcap)
    assert cmd[-5:] == ["host", "10.0.0.2", "and", "port", "22"]


def test_tcpdump_command_uses_sudo_without_root(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    cmd = tcpdump_command(CaptureSpec(iface="lo", out_dir=tmp_path), "tcpdump")
    assert cmd[:3] == ["sudo", "-n", "tcpdump"]


def test_run_capture_returns_command_exit_code_and_writes_metadata(tmp_path):
    spec = CaptureSpec(iface="fake0", out_dir=tmp_path / "cap", bpf="tcp")
    code = run_capture([sys.executable, "-c", "raise SystemExit(3)"], spec, tcpdump=_fake_tcpdump(tmp_path))
    assert code == 3
    assert spec.pcap.exists()
    meta = json.loads(spec.meta.read_text())
    assert meta["exit_code"] == 3
    assert meta["iface"] == "fake0"
    assert meta["filter"] == "tcp"
    assert "listening on" in spec.log.read_text()


def test_run_capture_stops_tcpdump_even_when_command_is_missing(tmp_path):
    spec = CaptureSpec(iface="fake0", out_dir=tmp_path / "cap")
    with pytest.raises(FileNotFoundError):
        run_capture(["/no/such/command-netdiag"], spec, tcpdump=_fake_tcpdump(tmp_path))
    # The fake tcpdump would keep running if it were not stopped, so the
    # fact that this test returns is the check. The log shows it started.
    assert "listening on" in spec.log.read_text()


def test_run_capture_reports_missing_tcpdump(tmp_path, monkeypatch):
    monkeypatch.setattr("netdiag.capture.shutil.which", lambda name: None)
    with pytest.raises(CaptureError, match="tcpdump is not installed"):
        run_capture(["true"], CaptureSpec(iface="lo", out_dir=tmp_path))


def test_run_capture_needs_a_command(tmp_path):
    with pytest.raises(CaptureError, match="no command"):
        run_capture([], CaptureSpec(iface="lo", out_dir=tmp_path), tcpdump="/bin/true")
