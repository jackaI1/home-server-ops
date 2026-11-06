import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "vuln_tracker", "--db", str(tmp_path / "demo.sqlite"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_cli_scan_update_report_and_inventory_exit(tmp_path):
    first = cli(
        tmp_path, "ingest", "tests/fixtures/nmap-before.xml", "--scope", "lab", "--on", "2026-01-01"
    )
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["new"] == 2
    update = cli(
        tmp_path,
        "update",
        "192.0.2.10",
        "CVE-2021-41773",
        "--status",
        "pending_validation",
        "--note",
        "Patched web server",
        "--owner",
        "Lab",
    )
    assert update.returncode == 0, update.stderr
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("asset,name,owner\n192.0.2.10,Web,Lab\n")
    report = cli(
        tmp_path,
        "report",
        "--as-of",
        "2026-01-10",
        "--format",
        "json",
        "--inventory",
        str(inventory),
        "--strict-inventory",
    )
    assert report.returncode == 3
    assert json.loads(report.stdout)["summary"]["overdue"] == 2
    text = cli(tmp_path, "report", "--as-of", "2026-01-10")
    assert "CVE-2021-41773" in text.stdout
    assert "overdue" in text.stdout.lower()


def test_cli_invalid_input_has_no_traceback_or_scan(tmp_path):
    bad = cli(
        tmp_path, "ingest", "tests/fixtures/nmap-before.xml", "--scope", "lab", "--on", "bad-date"
    )
    assert bad.returncode == 2
    assert "Traceback" not in bad.stderr
    report = cli(tmp_path, "report", "--format", "json")
    assert json.loads(report.stdout)["summary"]["scans"] == 0


def test_live_nmap_local_lab_and_socket_cleanup(tmp_path):
    if not shutil.which("nmap"):
        if os.environ.get("REQUIRE_NMAP") == "1":
            pytest.fail("Nmap is required for this CI job")
        pytest.skip("Install Nmap to run the loopback integration test")
    run = subprocess.run(
        [sys.executable, "scripts/run_lab.py", "--output", str(tmp_path / "lab")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert run.returncode == 0, run.stderr + run.stdout
    assert "Traceback" not in run.stderr
    result = json.loads((tmp_path / "lab/result.json").read_text())
    assert result["before"]["new"] == 1
    assert result["after"]["fixed"] == 1
    assert result["report"]["findings"][0]["status"] == "fixed"
    assert result["cleanup"]["socket_closed"] is True
    assert result["cleanup"]["server_thread_stopped"] is True
